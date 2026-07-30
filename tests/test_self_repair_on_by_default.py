"""Guard: self-repair + safety behaviours ship default-ON as System-tab toggles.

feat/self-repair-on-by-default flipped dormant self-repair/safety flags from
default-OFF to default-ON and exposed each as a runtime-mutable System-tab
toggle (settings_registry.SETTINGS -> the PATCH /api/control/config allowlist).
11 remain default-ON (SELF_REPAIR_FLAGS).

Two flags — ``precondition_gate_enabled`` and ``caching_issue_store_enabled``
(OPT_IN_AFTER_CACHE_FLAGS) — were reverted to default-OFF (#10846/#10845): the
precondition gate needs review_stored cache coverage the factory lacks on a
cold cache, so ON reroutes every READY issue back to plan forever and wedges
the full-machine pipeline (RC promotion + post-merge smoke). They stay runtime
toggles so an operator can opt in after confirming coverage.

``adr_touchpoint_auditor_loop_enabled`` was deliberately dropped from the flip
(kept default-OFF): it re-enables the activity-based ADR-drift auditor #10540
retired for a ~70% false-positive rate, and its triage sibling
``adr_drift_resolver_loop_enabled`` stays off — so its rollups would pile up
unhandled. It is pinned OFF here alongside the other landmines.

These tests fail-closed on:
  1. An accidental flip-back of any default-ON self-repair flag to False.
  2. An accidental flip-ON of the opt-in-after-cache flags.
  3. Dropping any flag from the runtime-mutable settings registry (which would
     make it un-toggleable from the System tab without a redeploy).

They also pin the deliberately-excluded landmines OFF so a future change can't
quietly fold them into the self-repair set.
"""

from __future__ import annotations

import pytest

from config import _ENV_BOOL_OVERRIDES, HydraFlowConfig
from settings_registry import (
    SETTINGS,
    build_settings_schema,
    mutable_field_names,
)

# The 11 flags flipped to default-ON and wired as System-tab toggles.
SELF_REPAIR_FLAGS: tuple[str, ...] = (
    "giveup_window_enabled",
    "escape_ledger_auto_diagnose_enabled",
    "sampled_audit_auto_adjudicate_enabled",
    "sandbox_failure_fixer_enabled",
    "close_verification_enabled",
    "judge_self_mod_fail_closed_enabled",
    "test_adequacy_verifier_fail_closed",
    "staging_enabled",
    "branch_gc_delete_enabled",
    "wiki_anchor_prune_enabled",
    "judge_independence_enabled",
)

# Reverted to default-OFF: opt-in-after-cache-coverage flags. #10791 flipped
# these ON, but the precondition gate needs review_stored cache coverage the
# factory lacks on a cold cache — so ON reroutes every READY issue back to
# plan forever and the full-machine pipeline wedges (RC promotion + post-merge
# smoke, #10846/#10845). They stay runtime-mutable System-tab toggles so an
# operator can opt in after confirming coverage; they just no longer default ON.
OPT_IN_AFTER_CACHE_FLAGS: tuple[str, ...] = (
    "precondition_gate_enabled",
    "caching_issue_store_enabled",
)

# Deliberately held OFF (disturbance dampener) / landmines that must stay off.
# adr_touchpoint_auditor_loop_enabled is dropped from the flip for the same
# reason adr_drift_resolver stays off: it is the retired (#10540) activity-based
# ADR-drift auditor (~70% false positives) whose triage sibling stays off.
EXCLUDED_OFF_FLAGS: tuple[str, ...] = (
    "disturbance_dampener_enabled",
    "rc_auto_recut_enabled",
    "adr_drift_resolver_loop_enabled",
    "adr_touchpoint_auditor_loop_enabled",
    "agent_unrestricted_tools",
)


@pytest.mark.parametrize("flag", SELF_REPAIR_FLAGS)
def test_self_repair_flag_defaults_true(flag: str) -> None:
    """Each flipped flag's *pure* Pydantic default (env-independent) is True."""
    # Arrange / Act
    default = HydraFlowConfig.model_fields[flag].default

    # Assert — use the field default, not an instance, so ambient env vars
    # (e.g. HYDRAFLOW_STAGING_ENABLED) can't mask an accidental flip-back.
    assert default is True, (
        f"{flag} must default True (self-repair on by default); "
        f"model_fields default is {default!r}"
    )


@pytest.mark.parametrize("flag", SELF_REPAIR_FLAGS)
def test_self_repair_flag_is_runtime_toggle(flag: str) -> None:
    """Each flipped flag is a runtime-mutable System-tab toggle."""
    # Assert — registry membership IS the PATCH mutable-field allowlist.
    assert flag in SETTINGS, f"{flag} missing from settings_registry.SETTINGS"
    assert flag in mutable_field_names(), (
        f"{flag} not in the runtime-mutable field set; it could not be "
        f"toggled off from the System tab without a redeploy"
    )


@pytest.mark.parametrize("flag", SELF_REPAIR_FLAGS)
def test_self_repair_flag_renders_as_bool_row(flag: str) -> None:
    """Each flipped flag renders in the settings schema as a bool toggle."""
    # Arrange
    schema = build_settings_schema(HydraFlowConfig())
    rows = {row["name"]: row for row in schema}

    # Assert
    assert flag in rows, f"{flag} produced no settings-schema row"
    assert rows[flag]["type"] == "bool", (
        f"{flag} should render as a bool toggle, got {rows[flag]['type']!r}"
    )
    assert rows[flag]["group"], f"{flag} has no settings group"


@pytest.mark.parametrize("flag", EXCLUDED_OFF_FLAGS)
def test_excluded_landmines_stay_off(flag: str) -> None:
    """The deliberately-excluded flags must remain default-OFF."""
    default = HydraFlowConfig.model_fields[flag].default
    assert default is False, (
        f"{flag} is a deliberately-excluded landmine and must default False; "
        f"got {default!r}"
    )


def test_env_bool_override_defaults_track_flipped_fields() -> None:
    """Every flipped flag present in _ENV_BOOL_OVERRIDES carries a True sentinel.

    The override loop only applies HYDRAFLOW_* env values when the field is at
    its default; the tuple's third element is that sentinel and must match the
    (now True) field default, otherwise the env var silently stops working.
    """
    table = {field: default for field, _env, default in _ENV_BOOL_OVERRIDES}
    for flag in SELF_REPAIR_FLAGS:
        if flag in table:
            assert table[flag] is True, (
                f"_ENV_BOOL_OVERRIDES sentinel for {flag} must be True to match "
                f"the flipped field default; got {table[flag]!r}"
            )


def test_all_flipped_flags_accounted_for() -> None:
    """Exactly 11 self-repair flags, all default-ON and all registered."""
    assert len(SELF_REPAIR_FLAGS) == 11
    assert len(set(SELF_REPAIR_FLAGS)) == 11
    mutable = mutable_field_names()
    for flag in SELF_REPAIR_FLAGS:
        assert HydraFlowConfig.model_fields[flag].default is True
        assert flag in mutable


@pytest.mark.parametrize("flag", OPT_IN_AFTER_CACHE_FLAGS)
def test_opt_in_flag_defaults_false(flag: str) -> None:
    """Opt-in-after-cache flags reverted to default-OFF (#10846/#10845).

    Enabling the precondition gate without review_stored cache coverage
    reroutes every READY issue back to plan forever, wedging the full-machine
    pipeline. These must default False; operators opt in via the System tab.
    """
    default = HydraFlowConfig.model_fields[flag].default
    assert default is False, (
        f"{flag} must default False (opt-in after cache coverage); got {default!r}"
    )


@pytest.mark.parametrize("flag", OPT_IN_AFTER_CACHE_FLAGS)
def test_opt_in_flag_still_runtime_toggle(flag: str) -> None:
    """Default-OFF, but still a runtime-mutable System-tab toggle to opt in."""
    assert flag in SETTINGS, f"{flag} missing from settings_registry.SETTINGS"
    assert flag in mutable_field_names(), (
        f"{flag} not runtime-mutable; an operator could not opt in from the "
        f"System tab without a redeploy"
    )


def test_opt_in_env_bool_override_sentinels_are_false() -> None:
    """_ENV_BOOL_OVERRIDES sentinel must track the (now False) field default.

    The override loop only applies HYDRAFLOW_* env values when the field is at
    its default; a stale True sentinel here would silently stop the env var
    from opting the gate on.
    """
    table = {field: default for field, _env, default in _ENV_BOOL_OVERRIDES}
    for flag in OPT_IN_AFTER_CACHE_FLAGS:
        if flag in table:
            assert table[flag] is False, (
                f"_ENV_BOOL_OVERRIDES sentinel for {flag} must be False to "
                f"match the reverted field default; got {table[flag]!r}"
            )
