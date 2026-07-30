"""Regression: the precondition gate must not default ON without cache coverage.

#10791 flipped ``precondition_gate_enabled`` (and ``caching_issue_store_enabled``)
to default-ON. With the gate on and no ``review_stored`` cache coverage — a cold
production cache, or the air-gapped sandbox whose seeds don't script a
``plan_review`` verdict — ``STAGE_PRECONDITIONS[READY].has_clean_review`` can
never be satisfied, so every READY issue is rerouted to ``plan`` forever. The
full-machine pipeline then advances nothing (``/api/issues/history`` stays
``{'items': []}``), which wedged RC promotion + the post-merge smoke from
2026-07-28 (RC #10845 / find #10846) and is a latent production cold-start risk.

Guard: both flags default OFF, so the gate is constructed disabled. The gate's
enabled expression mirrors ``service_registry``:
``enabled = issue_cache_enabled and precondition_gate_enabled``.
"""

from __future__ import annotations

from config import HydraFlowConfig


def test_precondition_and_cache_store_default_off() -> None:
    """Both flips reverted: env-independent Pydantic defaults are False."""
    fields = HydraFlowConfig.model_fields
    assert fields["precondition_gate_enabled"].default is False
    assert fields["caching_issue_store_enabled"].default is False


def test_gate_constructed_disabled_by_default() -> None:
    """The service_registry gate expression is False under defaults.

    ``issue_cache_enabled`` stays True (caching is fine); the gate is off
    because ``precondition_gate_enabled`` is off — so no READY issue is
    rerouted for a missing review_stored record on a cold cache.
    """
    fields = HydraFlowConfig.model_fields
    issue_cache_enabled = fields["issue_cache_enabled"].default
    precondition_gate_enabled = fields["precondition_gate_enabled"].default
    gate_enabled = issue_cache_enabled and precondition_gate_enabled
    assert gate_enabled is False, (
        "PreconditionGate must be constructed disabled by default; a cold "
        "cache with the gate on reroutes every READY issue to plan forever"
    )
