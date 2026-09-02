"""#11992: dials alone left seven runners reaching Anthropic directly.

The config gate shipped in #12019 required every ``*_provider`` dial to read
``"gateway"`` for the enforcement-canary repo. That covered the faces a dial
can name — and no more. ``BaseRunner._resolve_provider`` returns a hardcoded
``"claude"`` for any subclass that declares no ``PROVIDER_FIELD``, and seven of
the eleven concrete subclasses declare none. No dial can move those; the only thing that routes
them through the gateway is ``gateway_fleet_ratchet_enabled``, which rewrites a
still-claude spawn in ``base_runner``.

So a canary repo with every dial on ``"gateway"`` and the ratchet off shipped
the exact thing this criterion refuses — an ungoverned face — and the gate
passed it.

The regression is the *combination*: dials green, ratchet off. Either half
alone was already handled.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))

from base_runner import BaseRunner  # noqa: E402
from config import HydraFlowConfig  # noqa: E402

_GOVERNED = "acme/hydraflow"
_DIALS = tuple(
    sorted(n for n in HydraFlowConfig.model_fields if n.endswith("_provider"))
)


def test_every_dial_on_gateway_does_not_excuse_a_missing_fleet_ratchet() -> None:
    """The shipped bug: all dials green, ratchet off, gate passes."""
    with pytest.raises(ValueError, match="gateway_fleet_ratchet_enabled"):
        HydraFlowConfig(
            repo=_GOVERNED,
            gateway_enforcement_canary_repo=_GOVERNED,
            gateway_fleet_ratchet_enabled=False,
            execution_mode="docker",
            **dict.fromkeys(_DIALS, "gateway"),
        )


def test_a_dial_less_runner_resolves_to_claude_which_is_why_the_ratchet_is_required() -> (
    None
):
    """The premise the gate rests on, pinned so it cannot silently invert.

    These runners are named individually rather than swept: the point is not
    how many there are, it is that a dial cannot reach them at all. If a later
    change gives them a ``PROVIDER_FIELD``, this test says so, and the ratchet
    clause becomes worth re-justifying rather than silently redundant.
    """
    for mod_name, cls_name in (
        ("bug_reproducer", "BugReproducer"),
        ("hitl_runner", "HITLRunner"),
        ("research_runner", "ResearchRunner"),
        ("discover_runner", "DiscoverRunner"),
        ("shape_runner", "ShapeRunner"),
        ("plan_reviewer", "PlanReviewer"),
        ("diagnostic_runner", "DiagnosticRunner"),
    ):
        cls = getattr(importlib.import_module(mod_name), cls_name)
        assert issubclass(cls, BaseRunner)
        assert cls.PROVIDER_FIELD is None, (
            f"{cls_name} now declares a provider dial — the ratchet clause in "
            f"`_validate_governed_repo_has_no_ungoverned_face` rests on it not "
            f"having one; re-read that rationale before relying on it"
        )


def test_a_runner_that_does_declare_a_dial_is_the_contrast() -> None:
    """The decoy: without this, the assertion above could pass on a typo.

    ``PROVIDER_FIELD`` resolving to ``None`` for every class would also satisfy
    the loop above if the attribute name were misspelled. This proves the name
    is live.
    """
    from planner import PlannerRunner

    assert PlannerRunner.PROVIDER_FIELD is not None
