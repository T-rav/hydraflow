"""#11991 AC3: pin maintenance-provider inheritance BEFORE the legacy path goes.

P6b migrates the legacy `*_provider` dials into generated baseline policies.
The issue is explicit that this pin must land first:

    #11524/#11525 maintenance-provider inheritance is pinned **before** the
    legacy path is removed, so the pin is known-good against old behaviour.

`maintenance_provider` is one of the two dials `routing_baseline` deliberately
does NOT generate — it "is not a role rule, it is the value a caller naming no
provider inherits". That makes it the dial whose migration is most likely to
change behaviour silently, and #11853 is the precedent: `apply_credit_failover`
was correct and simply never called. A dial that stops steering does not raise;
it routes to a default that looks reasonable.

Measured against CURRENT behaviour, not remembered behaviour: #12083
(ADR-0147, route every role through the gateway) moved every one of these
roles off `claude` and onto `gateway`, so a pin written from memory would
have asserted a default that stopped being true hours earlier.

Both parametrisations iterate the PRODUCTION sets by reference, per
`docs/standards/parametrised_guards/README.md`. A seventh maintenance-dialled
role or a fifth inheriting stage is covered the day it is added, which a
hand-copied list would not be.
"""

from __future__ import annotations

import pytest

from config import (
    _MAINTENANCE_DIALED_ROLES,
    _STAGE_PROVIDER_SOURCE,
    HydraFlowConfig,
)

_INHERITING_STAGES = tuple(
    sorted(
        stage
        for stage, sources in _STAGE_PROVIDER_SOURCE.items()
        if "maintenance_provider" in sources
    )
)


def test_the_sets_this_file_reasons_about_are_not_empty() -> None:
    """Fail closed: an empty set makes every case below vacuously true."""
    assert _MAINTENANCE_DIALED_ROLES, "no maintenance-dialled roles to check"
    assert _INHERITING_STAGES, "no stage inherits maintenance_provider"


@pytest.mark.parametrize("role", sorted(_MAINTENANCE_DIALED_ROLES))
def test_a_dialled_role_inherits_the_maintenance_provider(role: str, tmp_path) -> None:
    """Setting the maintenance dial moves the whole role-set together.

    Provider AND model, because the seam applies them coherently — `zai` is
    the GLM harness and rejects a non-glm model, so a test that set only the
    provider would be rejected by the config validator rather than exercising
    the inheritance.
    """
    config = HydraFlowConfig(
        repo_root=tmp_path, maintenance_provider="zai", maintenance_model="glm-4.6"
    )

    assert getattr(config, f"{role}_provider") == "zai", (
        f"{role} no longer inherits maintenance_provider — it will keep "
        "routing to its own default while the operator believes the "
        "maintenance role-set moved (#11991 AC3)"
    )


@pytest.mark.parametrize("role", sorted(_MAINTENANCE_DIALED_ROLES))
def test_an_explicit_role_dial_still_wins(role: str, tmp_path) -> None:
    """The decoy: inheritance must not overwrite an operator's own choice.

    Without this, the assertion above passes against a build that slams every
    role to the maintenance value unconditionally — discarding per-role
    routing rather than inheriting into it.
    """
    config = HydraFlowConfig(
        repo_root=tmp_path,
        maintenance_provider="zai",
        maintenance_model="glm-4.6",
        **{f"{role}_provider": "gateway"},
    )

    assert getattr(config, f"{role}_provider") == "gateway"


@pytest.mark.parametrize("stage", _INHERITING_STAGES)
def test_an_inheriting_stage_resolves_through_the_maintenance_dial(
    stage: str, tmp_path
) -> None:
    """These stages own no dial; their source map must still point at it.

    They omit the provider on their `run_lightweight_agent` calls deliberately
    so the central seam performs the inheritance. If the mapping is dropped
    during P6b's migration the stage silently falls back rather than raising.
    """
    assert "maintenance_provider" in _STAGE_PROVIDER_SOURCE[stage]

    config = HydraFlowConfig(
        repo_root=tmp_path, maintenance_provider="zai", maintenance_model="glm-4.6"
    )
    resolved = {
        getattr(config, field, "claude") for field in _STAGE_PROVIDER_SOURCE[stage]
    }

    assert "zai" in resolved, (
        f"{stage} would resolve to {sorted(resolved)} with the maintenance "
        "dial set to zai — the stage stopped following the dial"
    )


@pytest.mark.parametrize("role", sorted(_MAINTENANCE_DIALED_ROLES))
def test_the_maintenance_dial_cannot_currently_select_claude(
    role: str, tmp_path
) -> None:
    """A KNOWN GAP, pinned so P6b's migration cannot quietly change it.

    `_apply_if_default` is guarded by `config.maintenance_provider != "claude"`,
    which treated `claude` as "unset". That was right when `claude` was the
    default. #12083 made `gateway` the default and the sentinel did not move,
    so an operator setting `maintenance_provider: claude` — to pull the
    maintenance role-set back off the gateway — gets no effect at all.

    This asserts the CURRENT behaviour rather than the desired one, on purpose.
    Changing which provider serves six roles is a spend decision, not a
    refactor, and it is reported on #11991 rather than made here. When it is
    fixed this test flips, and the flip should be deliberate and visible.

    The per-role dial remains a working escape hatch — pinned below.
    """
    config = HydraFlowConfig(repo_root=tmp_path, maintenance_provider="claude")

    assert getattr(config, f"{role}_provider") == "gateway"


def test_the_per_role_dial_is_still_an_escape_hatch(tmp_path) -> None:
    """Whatever the maintenance knob cannot express, the role dial still can."""
    config = HydraFlowConfig(repo_root=tmp_path, adr_review_provider="claude")

    assert config.adr_review_provider == "claude"
