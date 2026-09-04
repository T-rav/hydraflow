"""Every gateway-capable dial is watched for a bypass (#12125).

`_gateway_direct_harness_roles` is what the fleet ratchet uses to answer "what
is still routing around the gateway". It scanned two of the three dial groups.
`GATEWAY_INHERITED_PROVIDER_FIELDS` — `maintenance_provider` and
`retro_finder_provider` — was scanned by neither, and `config.py`'s own comment
on that group says why that is the wrong one to miss:

    `maintenance_provider` is the PARENT four caretaker roles inherit at their
    lightweight seam, so leaving it direct routes those four around the gateway
    no matter what the named dials say — the widest hole in the set.

So a deployment with `gateway_fleet_ratchet_enabled` and
`maintenance_provider: zai` passed the ratchet while five roles spawned on a
direct harness with a host credential, outside the gateway ledger. Pre-existing
and never kimi-specific; it has been true for z.ai since the group existed.

The cases below are parametrised over `GATEWAY_CAPABLE_PROVIDER_FIELDS` — the
union of all three groups — rather than over the group that was missed. A
guard written against the specific omission would be satisfied by adding one
more loop, and the next group added would be missed exactly the same way.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (  # noqa: E402
    GATEWAY_CAPABLE_PROVIDER_FIELDS,
    GATEWAY_INHERITED_PROVIDER_FIELDS,
    HydraFlowConfig,
    _gateway_direct_harness_roles,
)


def test_there_are_dials_to_guard() -> None:
    """Fail closed: an empty union makes every parametrised case vanish."""
    assert len(GATEWAY_CAPABLE_PROVIDER_FIELDS) >= 3
    assert GATEWAY_INHERITED_PROVIDER_FIELDS, "the missed group is empty"


def test_an_all_gateway_fleet_reports_no_bypass(tmp_path: Path) -> None:
    """The baseline. Without it, a function that reported every dial
    unconditionally would satisfy every case below."""
    assert _gateway_direct_harness_roles(HydraFlowConfig(repo_root=tmp_path)) == []


@pytest.mark.parametrize("dial", GATEWAY_CAPABLE_PROVIDER_FIELDS)
def test_a_dial_pointed_at_the_direct_claude_harness_is_reported(
    dial: str, tmp_path: Path
) -> None:
    """`claude` is a bypass on every dial shape, which is what makes it the
    value worth sweeping the whole union with.

    An agentic dial on `claude` spawns the CLI against Anthropic directly; a
    one-shot dial on `claude` does the same for its lightweight seam. Neither
    mints a virtual key, so neither appears in the gateway ledger — which is
    the thing the ratchet exists to notice.
    """
    config = HydraFlowConfig(repo_root=tmp_path, **{dial: "claude"})

    reported = _gateway_direct_harness_roles(config)

    assert any(row.startswith(f"{dial}=") for row in reported), (
        f"{dial} is on the direct claude harness and the ratchet did not "
        f"report it; reported={reported}"
    )


def test_a_direct_maintenance_dial_is_reported(tmp_path: Path) -> None:
    """The named defect, on the dial `config.py` calls the widest hole.

    Stated for `zai` rather than `claude` because that is the case that was
    silently passing: four caretaker roles inherit this dial, so a direct value
    here routes all of them around the gateway while every named dial still
    reads `gateway`.
    """
    config = HydraFlowConfig(
        repo_root=tmp_path, maintenance_provider="zai", maintenance_model="glm-4.6"
    )

    reported = _gateway_direct_harness_roles(config)

    assert any("maintenance_provider" in row for row in reported), (
        f"a direct maintenance_provider was not reported; reported={reported}"
    )


def test_a_one_shot_dial_on_an_http_face_is_not_a_harness_bypass(
    tmp_path: Path,
) -> None:
    """`retro_finder_provider: openrouter` is not a bypass, and must not be
    reported as one.

    The one-shot HTTP lanes never spawn a CLI at all — they are a direct POST,
    already their own billing identity, and deliberately excluded. Reporting
    them would make the ratchet's output unactionable, which is how a fleet
    gate stops being read.

    This is the decoy for the case above: a fix that simply reported every
    non-gateway value on every dial would pass every other test in this file
    and fail here.
    """
    config = HydraFlowConfig(repo_root=tmp_path, retro_finder_provider="openrouter")

    reported = _gateway_direct_harness_roles(config)

    assert not any("retro_finder_provider" in row for row in reported), (
        f"a one-shot HTTP face was reported as a harness bypass: {reported}"
    )


def test_an_inherited_dial_is_judged_by_its_own_shape(tmp_path: Path) -> None:
    """The two inherited dials do not share a rule, so the scan cannot use one.

    `maintenance_provider` is agentic-shaped (no `openrouter` in its choices)
    and `retro_finder_provider` is one-shot-shaped. Grouping them by where they
    are declared rather than by what they are would misjudge one of them
    whichever rule the group was given.
    """
    config = HydraFlowConfig(
        repo_root=tmp_path,
        maintenance_provider="zai",
        maintenance_model="glm-4.6",
        retro_finder_provider="zai",
    )

    reported = _gateway_direct_harness_roles(config)

    assert any("maintenance_provider" in row for row in reported)
    assert not any("retro_finder_provider" in row for row in reported)
