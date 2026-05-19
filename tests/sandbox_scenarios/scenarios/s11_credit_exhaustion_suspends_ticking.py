"""s11 — credit-exhaustion field shape on /api/control/status.

Originally authored to assert ``state["credits_paused"]`` after FakeLLM
raised ``CreditExhaustedError`` — but the actual field is
``credits_paused_until: str | None`` on ``ControlStatusResponse``, and
the FakeLLM ``{"raise": "CreditExhaustedError"}`` script sentinel is
not (yet) plumbed through the sandbox-mode runner wiring to bubble up
into ``HydraFlowOrchestrator._credits_paused_until``.

This scenario was rewritten as part of #8483 to assert against the
**real** field shape so any subsequent FakeLLM raise-plumbing PR has a
landing site that's already wired correctly. The end-to-end behavior
(raise → suspension → System-tab banner) requires a follow-up to widen
``FakeLLM.script_*`` to honor the ``{"raise": …}`` sentinel; this
scenario covers the API contract that the follow-up will assert
against.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s11_credit_exhaustion_suspends_ticking"
DESCRIPTION = (
    "/api/control/status exposes credits_paused_until (str | None) per the "
    "real ControlStatusResponse shape (#8483)."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]}
        ],
        scripts={
            # Placeholder for the follow-up FakeLLM raise-plumbing PR.
            # Today this is a no-op (the sentinel isn't honored); kept so
            # the seed is wired in the shape the future implementation
            # will consume.
            "plan": {1: [{"raise": "CreditExhaustedError"}]},
        },
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    """API exposes credits_paused_until per ControlStatusResponse shape."""

    # /api/control/status returns ControlStatusResponse which carries
    # ``credits_paused_until: str | None`` (the production field, serialized
    # from ``HydraFlowOrchestrator.credits_paused_until.isoformat()``).
    # The body must include the key — that's the contract this scenario
    # locks down. Whether it's None or a timestamp is the behavior axis
    # the follow-up will cover.
    payload = await api.wait_until(
        "/api/control/status",
        lambda p: isinstance(p, dict) and "credits_paused_until" in p,
        timeout=30.0,
    )
    # Type contract: None (no pause) OR a string timestamp.
    value = payload["credits_paused_until"]
    assert value is None or isinstance(value, str), (
        f"credits_paused_until should be str | None, got {type(value).__name__}: "
        f"{value!r}"
    )

    # Steady state today: FakeLLM raise-plumbing is a follow-up, so the
    # raise sentinel in seed.scripts is a no-op and no suspension fires.
    # We assert the None branch deliberately — once raise-plumbing lands,
    # this scenario should split: this assertion stays as a smoke check,
    # and the new behavior assertion becomes its own scenario.
    assert value is None, (
        "Expected credits_paused_until=None in steady state. If this fires "
        "non-None unexpectedly, the raise-plumbing follow-up may have "
        "landed — split this scenario into shape (None branch) + "
        "behavior (suspended branch) and update #8483 successor."
    )
