# tests/test_prompt_registry_completeness.py
"""Ratchet: every prompt builder in src/ is registered in PROMPT_REGISTRY.

Mirrors test_loop_fitness_completeness.py. A prompt builder that is not in
``scripts/audit_prompts.py``'s ``PROMPT_REGISTRY`` has no rendered fixture and
is never scored against the ADR-0087 rubric, so its structure drifts unseen —
the failure mode that let the registry fall to 25 of 65 builders between April
and July 2026 without anyone noticing.

The convention and the allowlist live in ``src/prompt_fitness.py``, not here:
``src`` owns what a prompt builder *is* and reports the current gap, and this
module asserts on it. The reverse direction (src importing from tests) is the
wrong dependency and was caught by the disturbance ratchet.
"""

from __future__ import annotations

import pytest

from prompt_fitness import (
    GRANDFATHERED,
    GRANDFATHERED_BURNDOWN_ORIGIN,
    GRANDFATHERED_DEADLINE,
    GRANDFATHERED_MAX,
    GRANDFATHERED_TARGET,
    discovered_builders,
    registered_modules,
)


def test_every_prompt_builder_is_registered() -> None:
    unregistered = sorted(
        set(discovered_builders()) - registered_modules() - GRANDFATHERED
    )
    assert not unregistered, (
        "Prompt builders with no PROMPT_REGISTRY entry (never rendered to a "
        f"fixture, never scored against ADR-0087): {unregistered}. Add an "
        "AuditTarget in scripts/audit_prompts.py plus a fixture under "
        "tests/fixtures/prompts/. New builders must NOT be added to "
        "GRANDFATHERED."
    )


def test_grandfathered_allowlist_only_shrinks() -> None:
    assert len(GRANDFATHERED) <= GRANDFATHERED_MAX, (
        f"GRANDFATHERED grew to {len(GRANDFATHERED)} (pinned at "
        f"{GRANDFATHERED_MAX}). The allowlist shrinks only: register the new "
        "builder instead of exempting it."
    )


def test_grandfathered_entries_still_have_builders() -> None:
    """A stale exemption silently re-opens the hole it was meant to track."""
    stale = sorted(GRANDFATHERED - set(discovered_builders()))
    assert not stale, (
        f"GRANDFATHERED lists modules with no prompt builders: {stale}. "
        "Remove them (and lower GRANDFATHERED_MAX) so the allowlist reflects "
        "real remaining work."
    )


def test_discovery_finds_the_known_registered_builders() -> None:
    """Guards the convention itself: if discovery breaks, the ratchet is blind."""
    discovered = discovered_builders()
    for module in ("triage", "planner", "agent", "reviewer"):
        assert module in discovered, (
            f"AST discovery found no prompt builder in src/{module}.py, but "
            "PROMPT_REGISTRY registers one. The naming convention in "
            "_BUILDER_NAME (src/prompt_fitness.py) has drifted from the code."
        )


# --------------------------------------------------------------------------
# Burn-down. The ratchet above stops the gap growing; it does not make it
# close. An untouched allowlist stays green forever, which is the same
# measured-but-not-enforced pattern one level down. This turns coverage debt
# into a dated commitment: past the deadline the build fails until either the
# backfill lands or the schedule is renegotiated in a commit that says why.
# --------------------------------------------------------------------------


def test_coverage_debt_is_burned_down_on_schedule() -> None:
    from datetime import date  # noqa: PLC0415

    deadline = date.fromisoformat(GRANDFATHERED_DEADLINE)
    today = date.today()
    remaining = len(GRANDFATHERED)
    if today <= deadline or remaining <= GRANDFATHERED_TARGET:
        return
    origin_date, origin_count = GRANDFATHERED_BURNDOWN_ORIGIN
    pytest.fail(
        f"Prompt-coverage burn-down missed its deadline: {remaining} module(s) "
        f"still unregistered on {today}, target {GRANDFATHERED_TARGET} by "
        f"{GRANDFATHERED_DEADLINE} (started at {origin_count} on {origin_date}).\n"
        "Either register the remaining builders, or move "
        "GRANDFATHERED_DEADLINE in src/prompt_fitness.py in a commit that "
        "states why the debt is being carried longer. Silently carrying it is "
        "the failure this test exists to prevent."
    )


def test_burndown_schedule_is_coherent() -> None:
    """A schedule that cannot be checked is decoration."""
    from datetime import date  # noqa: PLC0415

    origin_date, origin_count = GRANDFATHERED_BURNDOWN_ORIGIN
    assert date.fromisoformat(GRANDFATHERED_DEADLINE) > date.fromisoformat(
        origin_date
    ), "GRANDFATHERED_DEADLINE must be after the burn-down origin date"
    assert origin_count > GRANDFATHERED_TARGET, (
        f"GRANDFATHERED_TARGET ({GRANDFATHERED_TARGET}) must be below the "
        f"origin count ({origin_count}), or the schedule commits to nothing"
    )
    assert len(GRANDFATHERED) <= origin_count, (
        f"the allowlist ({len(GRANDFATHERED)}) exceeds its burn-down origin "
        f"({origin_count}) — the debt grew, which the ratchet should have caught"
    )


def test_every_registry_category_appears_in_the_report() -> None:
    """A target in an unlisted category is silently dropped from the report.

    ``write_markdown`` iterates ``_CATEGORY_ORDER`` and skips anything else, so
    a target given a novel category (there is no "Shape" category, for example)
    is scored but never printed — registered, measured, and invisible, which is
    the reporting equivalent of the gap this module exists to close.
    """
    from scripts.audit_prompts import (  # noqa: PLC0415
        _CATEGORY_ORDER,
        PROMPT_REGISTRY,
    )

    known = set(_CATEGORY_ORDER)
    used = {t.category for t in PROMPT_REGISTRY}
    assert not used - known, (
        f"PROMPT_REGISTRY uses categories absent from _CATEGORY_ORDER: "
        f"{sorted(used - known)}. These targets are scored but omitted from "
        "the generated report. Add the category to _CATEGORY_ORDER in "
        "scripts/audit_prompts.py, or reuse an existing one."
    )


def test_registry_qualnames_resolve_to_the_module_they_name() -> None:
    """A re-export resolves fine but credits the wrong module.

    ``registered_modules()`` matches the dotted module name against the text of
    the registry, so registering ``audit.adjudicate``'s builder via a call-site
    re-export (``sampled_audit_loop.build_adjudication_prompt``) would render
    and score happily while leaving ``audit.adjudicate`` in the allowlist —
    coverage credited to a module that does not own the prompt. This asserts
    every qualname resolves to exactly the module it names.
    """
    from scripts.audit_prompts import (  # noqa: PLC0415
        PROMPT_REGISTRY,
        _resolve_owner,
    )

    for target in PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        module, attrs = _resolve_owner(target.builder_qualname)
        resolved = f"{module.__name__}." + ".".join(attrs)
        assert resolved == target.builder_qualname, (
            f"{target.name}: declared {target.builder_qualname} but resolves "
            f"to {resolved}. Register the owning module's path, not a re-export."
        )
