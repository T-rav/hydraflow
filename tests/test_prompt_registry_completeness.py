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
    EXCLUDED_MODULES,
    EXCLUDED_MODULES_MAX,
    GRANDFATHERED,
    GRANDFATHERED_BURNDOWN_ORIGIN,
    GRANDFATHERED_DEADLINE,
    GRANDFATHERED_MAX,
    GRANDFATHERED_SCHEDULE_LOG,
    GRANDFATHERED_TARGET,
    PLACEHOLDER_LEAK_EXEMPT,
    PLACEHOLDER_LEAK_EXEMPT_MAX,
    UNRENDERABLE_MAX,
    all_builders,
    discovered_builders,
    registered_builders,
)


def test_every_prompt_builder_is_registered() -> None:
    """Per BUILDER, not per module.

    Module granularity reported 100% coverage while five builders inside
    already-"covered" modules had no fixture and no score — a module with five
    builders and one fixture counted as fully covered. Two of them
    (``reviewer._build_precheck_prompt``, ``spec_match.build_self_review_prompt``)
    had been invisible that way since the registry was built in April.
    """
    grandfathered_builders = {
        b for b in all_builders() if b.rsplit(".", 1)[0] in GRANDFATHERED
    }
    unregistered = sorted(
        all_builders() - registered_builders() - grandfathered_builders
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
    # ``agent`` and ``reviewer`` are packages (#11547 batches 4 and 5); their
    # builders live in ``<pkg>._prompts``, which is the module discovery reports.
    for module in ("triage", "planner", "agent._prompts", "reviewer._prompts"):
        assert module in discovered, (
            f"AST discovery found no prompt builder in src/{module.replace('.', '/')}.py, but "
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


#: A single burn-down window may not exceed this many days from its origin
#: (#10861). Without this, ``GRANDFATHERED_DEADLINE`` moves for free — pushing it
#: a year out keeps every test green and carries the debt indefinitely. A
#: *legitimate* extension moves the origin forward too (re-declaring the debt at
#: that date), which keeps the window bounded; a bare deadline push does not.
_MAX_BURNDOWN_WINDOW_DAYS = 180


def _burndown_window_days(deadline: str, origin: str) -> int:
    from datetime import date  # noqa: PLC0415

    return (date.fromisoformat(deadline) - date.fromisoformat(origin)).days


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
    window = _burndown_window_days(GRANDFATHERED_DEADLINE, origin_date)
    assert window <= _MAX_BURNDOWN_WINDOW_DAYS, (
        f"the burn-down window is {window} days ({origin_date} → "
        f"{GRANDFATHERED_DEADLINE}), over the {_MAX_BURNDOWN_WINDOW_DAYS}-day cap "
        f"(#10861). The deadline cannot be pushed out for free — to carry the "
        f"debt longer, move GRANDFATHERED_BURNDOWN_ORIGIN forward as well, which "
        f"re-declares the debt at a new date and keeps the window bounded."
    )


def test_the_window_cap_rejects_a_free_year_long_extension() -> None:
    # The exact #10861 scenario: pushing the deadline a year past the origin
    # without moving the origin must exceed the cap, so it can't pass silently.
    origin_date, _ = GRANDFATHERED_BURNDOWN_ORIGIN
    from datetime import date  # noqa: PLC0415

    a_year_out = date.fromisoformat(origin_date).replace(
        year=date.fromisoformat(origin_date).year + 1
    )
    assert (
        _burndown_window_days(a_year_out.isoformat(), origin_date)
        > _MAX_BURNDOWN_WINDOW_DAYS
    )


# The window cap bounds how *far* the deadline can reach; the receipt gate below
# is the orthogonal "who authorized this" half of ADR-0116 §5a's "a commit that
# says why" (#10861). The deadline is derived from an append-only schedule log
# pairing every value it has taken with the issue/PR that moved it — so a bare
# deadline edit that carries no fresh receipt cannot pass silently.


def test_deadline_moves_carry_a_receipt() -> None:
    import re  # noqa: PLC0415
    from datetime import date  # noqa: PLC0415

    assert GRANDFATHERED_SCHEDULE_LOG, "the schedule log must have at least one row"

    deadlines = [row[0] for row in GRANDFATHERED_SCHEDULE_LOG]
    receipts = [row[1] for row in GRANDFATHERED_SCHEDULE_LOG]

    # The live deadline is the last row — the derivation must not have drifted.
    assert deadlines[-1] == GRANDFATHERED_DEADLINE, (
        f"GRANDFATHERED_DEADLINE ({GRANDFATHERED_DEADLINE}) must equal the last "
        f"schedule-log deadline ({deadlines[-1]})"
    )

    # A move means a *new* row with a *new* receipt: duplicate deadlines or a
    # reused receipt means the deadline was pushed without a fresh authorization.
    assert len(deadlines) == len(set(deadlines)), (
        f"duplicate deadline in GRANDFATHERED_SCHEDULE_LOG: {deadlines}"
    )
    assert len(receipts) == len(set(receipts)), (
        f"a deadline move reused a receipt in GRANDFATHERED_SCHEDULE_LOG: "
        f"{receipts} (#10861). Cite the issue/PR that authorized THIS move."
    )

    for receipt in receipts:
        assert re.fullmatch(r"#\d+", receipt), (
            f"schedule-log receipt {receipt!r} is not an issue/PR reference like "
            f"#1234 (#10861) — 'a commit that says why' needs a receipt, not prose."
        )

    # Every logged deadline must be a real date, and they advance in order, so
    # the log reads as a genuine renegotiation history rather than a scratch pad.
    parsed = [date.fromisoformat(d) for d in deadlines]
    assert parsed == sorted(parsed), (
        f"schedule-log deadlines must be in chronological order: {deadlines}"
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


def test_unrenderable_targets_are_pinned_and_justified() -> None:
    """``unrenderable=True`` registers a prompt that is never scored.

    It is a legitimate escape for a builder that genuinely cannot be rendered,
    but it is also a hatch: flip the flag, delete the fixture and the baseline
    entry, and every assertion here stays green while a High-severity prompt
    leaves the measured set. ``registered_modules()`` no longer credits
    coverage for one; this pins the count and forces a stated reason.
    """
    from scripts.audit_prompts import PROMPT_REGISTRY  # noqa: PLC0415

    unrenderable = [t for t in PROMPT_REGISTRY if t.unrenderable]
    assert len(unrenderable) <= UNRENDERABLE_MAX, (
        f"{len(unrenderable)} unrenderable targets (pinned at "
        f"{UNRENDERABLE_MAX}): {[t.name for t in unrenderable]}. An "
        "unrenderable target is registered but never scored — fix the fixture "
        "rather than exempting the prompt."
    )
    unexplained = [t.name for t in unrenderable if not t.unrenderable_reason.strip()]
    assert not unexplained, (
        f"unrenderable targets with no stated reason: {unexplained}. An "
        "exemption with a reason is a decision; without one it is rot."
    )


def test_excluded_modules_are_pinned_and_still_justified() -> None:
    """EXCLUDED_MODULES is the one allowlist with no ratchet on it.

    GRANDFATHERED has three guards; this had none, so a module with a real
    builder could be excluded outright and the diff would read as *progress* —
    the allowlist gets smaller while a prompt goes unmeasured. Pinned by size,
    and every entry must still name why it is not model-bound text.
    """
    assert len(EXCLUDED_MODULES) <= EXCLUDED_MODULES_MAX, (
        f"EXCLUDED_MODULES grew to {len(EXCLUDED_MODULES)} (pinned at "
        f"{EXCLUDED_MODULES_MAX}). Excluding a module hides its builders from "
        "discovery entirely — register the prompt instead."
    )
    unexplained = sorted(m for m, why in EXCLUDED_MODULES.items() if not why.strip())
    assert not unexplained, (
        f"EXCLUDED_MODULES entries with no reason: {unexplained}. Every "
        "exclusion states why the module is not model-bound text."
    )


def test_placeholder_leak_exemptions_are_pinned_and_justified() -> None:
    """The leak gate has one escape; it must stay small and stay explained."""
    assert len(PLACEHOLDER_LEAK_EXEMPT) <= PLACEHOLDER_LEAK_EXEMPT_MAX, (
        f"PLACEHOLDER_LEAK_EXEMPT grew to {len(PLACEHOLDER_LEAK_EXEMPT)} "
        f"(pinned at {PLACEHOLDER_LEAK_EXEMPT_MAX}). A literal placeholder "
        "reaching the model is a bug; exempting the prompt is not the fix "
        "unless its payload is genuinely arbitrary source code."
    )
    unexplained = sorted(
        n for n, why in PLACEHOLDER_LEAK_EXEMPT.items() if not why.strip()
    )
    assert not unexplained, f"exemptions with no reason: {unexplained}"
    from scripts.audit_prompts import PROMPT_REGISTRY  # noqa: PLC0415

    known = {t.name for t in PROMPT_REGISTRY}
    stale = sorted(set(PLACEHOLDER_LEAK_EXEMPT) - known)
    assert not stale, (
        f"PLACEHOLDER_LEAK_EXEMPT names prompts not in the registry: {stale}. "
        "A stale exemption silently covers whatever takes that name next."
    )
