"""#12105: a seam declaration must describe the mechanism that exists.

The architecture guard added alongside this pins the general property — every
`config_disable` key names a flag, and that flag is provably pinned off. This
pins the two SPECIFIC untruths that property was written after, so neither can
come back under a passing general check.

1. `health_monitor_loop` was declared `config_disable` module-wide while only
   one of its two spawns was behind a flag. `_check_stale_code` is behind none:
   it runs on the air-gapped network. #11392 moved that spawn OUT of
   GRANDFATHERED_SPAWN_BASELINE and INTO the declaration to satisfy the
   shrink-only rule — the spawn did not become air-gapped, its label changed.
   A shrink-only ratchet rewards exactly that move, so it needs a pin.

2. The `bounded_offline_failure` kind exists so "safe because it fails fast"
   stops being filed under a kind that means "cannot run". If it were dropped
   and the path re-declared `config_disable`, the general guard would demand a
   flag — and the tempting fix is to invent one rather than notice the spawn is
   real.
"""

from __future__ import annotations

from mockworld.sandbox_main import (
    CONFIG_DISABLE_FLAGS,
    SANDBOX_SEAMS,
    SEAM_KINDS,
)

_STALE_CODE = "health_monitor_loop::HealthMonitorFreshnessMixin._check_stale_code"
_LEDGER = "health_monitor_loop::HealthMonitorFleetVitalsMixin._fleet_change_ledger"


def test_the_stale_code_fetch_is_not_claimed_to_be_config_disabled() -> None:
    """It runs on the air-gapped network — no flag turns it off."""
    assert SANDBOX_SEAMS.get(_STALE_CODE) == "bounded_offline_failure"
    assert _STALE_CODE not in CONFIG_DISABLE_FLAGS, (
        "no config flag disables the stale-code fetch; naming one here would "
        "make the general guard green over a claim that is false"
    )


def test_health_monitor_is_not_declared_config_disable_module_wide() -> None:
    """The module-wide claim was half true, which is the bug (#12105)."""
    assert "health_monitor_loop" not in SANDBOX_SEAMS, (
        "a module-wide seam for health_monitor_loop covers both spawn paths "
        "with one mechanism again — they do not share one"
    )
    assert SANDBOX_SEAMS.get(_LEDGER) == "config_disable"
    assert CONFIG_DISABLE_FLAGS[_LEDGER] == ("fleet_vitals_enabled",)


def test_the_bounded_offline_failure_kind_still_exists() -> None:
    """Removing the kind forces the honest declaration back into a false one."""
    assert "bounded_offline_failure" in SEAM_KINDS
