"""#12125 — the fleet ratchet accepted the bypass it exists to refuse.

`gateway_fleet_ratchet_enabled` is the operator's statement that every
gateway-capable role goes through the proxy. `_validate_gateway_fleet_profile`
enforces it at config load by refusing any role still on a direct harness,
using `_gateway_direct_harness_roles` to find them.

That function scanned two of the three dial groups.
`GATEWAY_INHERITED_PROVIDER_FIELDS` was scanned by neither — so a config with
the ratchet ON and `maintenance_provider` pointed at a direct harness **loaded
successfully**, and the four caretaker roles that inherit that dial spawned
with a host credential outside the gateway ledger. The ratchet reported
compliance for the exact arrangement it was switched on to prevent.

These pin the observable end rather than the reporting function: what changed
for an operator is that this configuration no longer starts.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from config import HydraFlowConfig  # noqa: E402


def _armed(tmp_path: Path, **dials: str) -> HydraFlowConfig:
    return HydraFlowConfig(
        repo_root=tmp_path,
        gateway_fleet_ratchet_enabled=True,
        execution_mode="docker",
        **dials,
    )


def test_the_ratchet_refuses_a_direct_maintenance_dial(tmp_path: Path) -> None:
    """The defect. This configuration used to load.

    `maintenance_provider` is the parent four caretaker roles inherit at the
    lightweight seam, so a direct value here routes all of them around the
    gateway while every named dial still reads `gateway` — which is why
    `config.py` calls this group the widest hole in the set.
    """
    with pytest.raises(ValueError, match="maintenance_provider"):
        _armed(tmp_path, maintenance_provider="zai", maintenance_model="glm-4.6")


def test_the_ratchet_refuses_a_direct_retro_finder_dial(tmp_path: Path) -> None:
    """The other half of the group, and it needs the other rule.

    `retro_finder_provider` is one-shot-shaped, so only `claude` is a harness
    bypass on it. A fix that gave the whole inherited group the agentic rule
    would pass the case above and misjudge this one.
    """
    with pytest.raises(ValueError, match="retro_finder_provider"):
        _armed(tmp_path, retro_finder_provider="claude")


def test_the_ratchet_still_allows_a_one_shot_http_face(tmp_path: Path) -> None:
    """The decoy. `retro_finder_provider: openrouter` is not a bypass.

    The one-shot HTTP lanes never spawn a CLI, are already their own billing
    identity, and are allowed by design — the error message says so. Without
    this case, a fix that simply refused every non-gateway value on every dial
    would satisfy both tests above while breaking configurations the ratchet
    was always meant to permit.
    """
    assert _armed(tmp_path, retro_finder_provider="openrouter")


def test_an_all_gateway_fleet_still_starts(tmp_path: Path) -> None:
    """The baseline the ratchet exists to allow."""
    assert _armed(tmp_path)
