"""Every provider dial defaults to the gateway (ADR-0147).

The gateway ledger is the only record carrying per-spawn attribution — role,
spawn, session, issue, PR — in one provider-agnostic schema. A dial defaulting
to a direct backend spends money that reaches no such record: the 2026-09-02
audit found that ledger holding 908 rows from ONE provider over two days, dead
for a fortnight, while the proxy ran and every dial pointed around it.

Both assertions are parametrised over the dials themselves, by reference, so a
role added tomorrow is covered without anyone remembering this file — the
parametrised-guards standard's rule, and the reason neither list is written out
here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from config import (  # noqa: E402
    GATEWAY_CAPABLE_PROVIDER_FIELDS,
    HydraFlowConfig,
)

_DIALS = sorted(n for n in HydraFlowConfig.model_fields if n.endswith("_provider"))


def test_there_are_dials_to_guard() -> None:
    """The decoy: an empty set makes every parametrised check below vacuous."""
    assert len(_DIALS) >= 13, f"only {len(_DIALS)} dials found — did they move?"


@pytest.mark.parametrize("dial", _DIALS)
def test_the_dial_defaults_to_the_gateway(dial: str) -> None:
    default = HydraFlowConfig.model_fields[dial].default

    assert default == "gateway", (
        f"{dial} defaults to {default!r}. Spend on a direct backend reaches no "
        "ledger with per-spawn attribution. Route it through the gateway, or "
        "supersede ADR-0147 with a decision saying why this role is exempt."
    )


def test_the_capable_set_covers_every_dial() -> None:
    """The tuple is the single source the ratchet and validators consume.

    A dial defaulting to `gateway` while absent from
    `GATEWAY_CAPABLE_PROVIDER_FIELDS` is the drift that matters: the default
    routes it, but the ratchet and the governed-repo gate would not know it
    exists, so the two halves would disagree about what "everything" means.
    """
    assert set(GATEWAY_CAPABLE_PROVIDER_FIELDS) == set(_DIALS), (
        "capable set and dial set have diverged: "
        f"only in capable={sorted(set(GATEWAY_CAPABLE_PROVIDER_FIELDS) - set(_DIALS))}, "
        f"only in dials={sorted(set(_DIALS) - set(GATEWAY_CAPABLE_PROVIDER_FIELDS))}"
    )


@pytest.mark.parametrize("dial", _DIALS)
def test_the_dial_keeps_a_direct_escape_hatch(dial: str) -> None:
    """Gateway-by-default, not gateway-only.

    `credit_failover` reroutes a spawn whose provider is `claude` when
    subscription credit is exhausted, and the air-gapped sandbox has no gateway
    to reach. Removing the literal would break both; the DEFAULT is the lever.
    """
    assert "claude" in str(HydraFlowConfig.model_fields[dial].annotation), (
        f"{dial} lost its direct-backend escape hatch"
    )
