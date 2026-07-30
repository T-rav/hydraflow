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

from prompt_fitness import (
    GRANDFATHERED,
    GRANDFATHERED_MAX,
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
