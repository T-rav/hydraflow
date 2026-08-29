"""Every background loop must be driven by a MockWorld scenario. Shrink-only.

``docs/standards/testing/README.md`` says a load-bearing feature ships unit +
MockWorld scenario + sandbox e2e, and that "skipping a layer is a procedural
failure, not a judgment call". The standard was written down and **nothing
enforced it** — the rule depended on an author remembering it, which is the
same class of failure as a guard that was never wired.

The nearest thing that existed, ``tests/scenarios/catalog/
test_catalog_completeness.py``, requires every loop in ``bg_loop_registry`` to
have a *catalog builder*. That is a weaker claim than it reads as: a builder is
a construction recipe, and it can sit in ``loop_registrations.py`` forever
without a single test calling it. This gate asks the question that one does
not — **is the loop actually exercised?**

Why loops are the subject, and not "features": a feature is not enumerable, so
a gate keyed on one can never say how much it is missing and can never notice
that it stopped looking. Loops are enumerable, they are the unit the standard
names ("MockWorld scenarios catch integration bugs unit tests can't see"), and
``arch.extractors.loops.extract_loops`` already enumerates them for the
published loop registry. The subject is borrowed from that extractor rather
than re-globbed — see ``mockworld_scenario_scan`` for why a fresh
``src/*_loop.py`` glob would have been the bug, not the gate.

**State at introduction: 64 loops, 64 covered, snapshot EMPTY.** The audit that
produced this gate went looking for a coverage hole at loop granularity and did
not find one, so this ratchet is a lock rather than a cleanup: it exists to
stop the 65th loop landing without a scenario, which is the only way this
number has ever moved. Falling is impossible from zero; the grandfather list is
here so a future loop that genuinely cannot be driven has a reviewed place to
say so rather than the gate being deleted to make it green.
"""

from __future__ import annotations

import json

import pytest

from tests.architecture.mockworld_scenario_scan import (
    REPO_ROOT,
    builder_reachable_classes,
    catalog_builder_keys,
    covered_loops,
    loop_subjects,
    scenario_files,
    uncovered_loops,
)

_BASELINE_REL = "tests/architecture/mockworld_loop_scenario_baseline.json"

#: The subject, by reference: every ``BaseBackgroundLoop`` subclass in ``src/``.
#: Registered in ``guard_enumeration_registry`` as a SUBJECT — a class dropped
#: from here stops being asked for a scenario while still looking guarded.
LOOP_CLASS_NAMES: tuple[str, ...] = tuple(
    subject.class_name for subject in loop_subjects()
)

# --- Anti-vacuity floors ---------------------------------------------------
# Not round numbers picked to look careful — each is comfortably below the
# live count (64 loops / 196 scenario files / 64 covered) and comfortably
# above anything a broken scan would produce. A scan that lost its root, its
# extractor or its AST walk returns 0 or a handful, and every assertion below
# compares a set difference that is empty over an empty world. This session
# found TWELVE guards that had stopped observing their subjects while staying
# green; the assumption here is that this one is blind until proven otherwise.
_MIN_LOOPS = 50
_MIN_SCENARIO_FILES = 100
_MIN_COVERED = 50


def _load_baseline() -> dict[str, list[str]]:
    return json.loads((REPO_ROOT / _BASELINE_REL).read_text(encoding="utf-8"))


def _grandfathered() -> frozenset[str]:
    """Live grandfathered set = ``baseline_snapshot - resolved``."""
    baseline = _load_baseline()
    return frozenset(baseline["baseline_snapshot"]) - frozenset(baseline["resolved"])


# ---------------------------------------------------------------------------
# Anti-vacuity: prove the scan can see its subject before believing its verdict
# ---------------------------------------------------------------------------


def test_the_scan_actually_has_a_subject() -> None:
    """A run that measured nothing must fail, not pass.

    Every other assertion in this file is "a set difference is empty", and
    every set difference is empty over an empty world. So a scan that
    collected no loops (wrong root, ``extract_loops`` re-pointed, ``src/``
    missing in a sparse checkout) or no scenarios (``tests/scenarios``
    renamed, the ``test_*.py`` glob no longer matching) reports a serene green
    while measuring its subject not at all.
    """
    loops = loop_subjects()
    scenarios = scenario_files()
    covered = covered_loops()

    assert len(loops) >= _MIN_LOOPS, (
        f"The loop scan found {len(loops)} BaseBackgroundLoop subclasses under "
        f"{REPO_ROOT / 'src'} (floor {_MIN_LOOPS}). The repo has had 60+ for "
        "months, so this is a broken enumeration, not a shrinking one — every "
        "coverage assertion below would pass vacuously. Check that "
        "arch.extractors.loops.extract_loops still walks src/ and still "
        "recognises the BaseBackgroundLoop base."
    )
    assert len(scenarios) >= _MIN_SCENARIO_FILES, (
        f"The scenario scan found {len(scenarios)} files under "
        f"{REPO_ROOT / 'tests' / 'scenarios'} (floor {_MIN_SCENARIO_FILES}). "
        "With no scenarios every loop reads as uncovered, so this fails loudly "
        "rather than reporting 64 spurious breaches."
    )
    assert len(covered) >= _MIN_COVERED, (
        f"Only {len(covered)} loops resolved to a driving scenario (floor "
        f"{_MIN_COVERED}). Both needles — a catalog key passed to "
        "run_with_loops/instantiate, and direct construction of the loop "
        "class — may have stopped matching at once, which is what happens "
        "when the scenario idiom changes. Read mockworld_scenario_scan and "
        "add the new spelling; do not lower this floor."
    )


def test_the_coverage_needle_rejects_a_loop_nothing_drives() -> None:
    """The other direction: coverage must be a question with a ``False``.

    ``covered_loops()`` answering ``True`` for everything is indistinguishable
    from a green gate, and is precisely how a gate masked by an over-broad
    match ships. A class name no scenario has ever heard of must come back
    uncovered.
    """
    assert "NeverWrittenSentinelLoop" not in covered_loops(), (
        "The coverage map claims a fabricated loop is driven by a scenario, "
        "so its matching is over-broad and every green below is meaningless."
    )


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("loop_class", LOOP_CLASS_NAMES)
def test_every_loop_is_driven_by_a_mockworld_scenario(loop_class: str) -> None:
    """One red test per loop that no scenario drives, naming the loop.

    Every parameter asserts something — a grandfathered loop is NOT skipped.
    A runtime skip would be an ignored active test (caught by
    ``test_no_ignored_active_tests``), and worse, it would let an exemption
    outlive its reason silently. So the grandfathered branch asserts the
    exemption is still EARNED: the moment such a loop gains a scenario, this
    reddens and tells you to bank the win in ``resolved``.
    """
    covered = loop_class in covered_loops()

    if loop_class in _grandfathered():
        assert not covered, (
            f"{loop_class} is grandfathered as uncovered in {_BASELINE_REL}, "
            "but a MockWorld scenario now drives it. Move it into the "
            "`resolved` list so the live grandfathered set shrinks — that is "
            "how this ratchet is paid down, and an exemption nobody removes "
            "is an exemption that stops meaning anything."
        )
        return

    assert covered, (
        f"{loop_class} has no MockWorld scenario. docs/standards/testing/"
        "README.md requires one: unit tests are blind to the loop's "
        "integration with its ports, and that is the layer this loop is "
        "missing.\n\n"
        "Add a scenario under tests/scenarios/ that either:\n"
        "  (a) drives it through the catalog —\n"
        '      await world.run_with_loops(["<catalog_key>"], cycles=1)\n'
        "      with a builder registered in "
        "tests/scenarios/catalog/loop_registrations.py; or\n"
        "  (b) constructs the loop class directly in the scenario body.\n\n"
        "A docstring naming the loop is NOT coverage — the scan reads the "
        "AST, not the file text, on purpose.\n\n"
        f"Do not add {loop_class} to {_BASELINE_REL}: baseline_snapshot is a "
        "frozen literal and this ratchet only shrinks."
    )


def test_the_ratchet_only_shrinks() -> None:
    """No loop may be uncovered unless the frozen snapshot already named it."""
    breaches = sorted(set(uncovered_loops()) - _grandfathered())

    assert not breaches, (
        "Loops with no MockWorld scenario that the frozen baseline does not "
        f"grandfather: {breaches}.\n\n"
        "This is the aggregate view of the per-loop failures above; fix those."
    )


# ---------------------------------------------------------------------------
# Baseline hygiene — a grandfather list that rots is a disabled ratchet
# ---------------------------------------------------------------------------


def test_baseline_entries_name_real_loops() -> None:
    """A snapshot id that no longer names a loop is dead weight, not progress.

    A renamed or deleted loop leaves its id behind; a shrink-only ratchet
    reads the disappearance as the one direction it allows without complaint,
    and the entry sits there forever excusing nothing.
    """
    baseline = _load_baseline()
    known = set(LOOP_CLASS_NAMES)
    named = set(baseline["baseline_snapshot"]) | set(baseline["resolved"])
    stale = sorted(named - known)

    assert not stale, (
        f"{_BASELINE_REL} names loops that no longer exist: {stale}. They were "
        "renamed or deleted. Remove them from both lists — an entry that "
        "matches nothing excuses nothing."
    )


def test_grandfathered_loops_are_still_uncovered() -> None:
    """A grandfathered loop that gained a scenario must be marked resolved.

    Otherwise the exemption outlives the reason for it, and the next reader
    cannot tell which entries are real debt.
    """
    healed = sorted(_grandfathered() & set(covered_loops()))

    assert not healed, (
        f"These loops are grandfathered in {_BASELINE_REL} but now have a "
        f"MockWorld scenario: {healed}. Move them into the `resolved` list so "
        "the live grandfathered set shrinks — that is how this ratchet is "
        "paid down."
    )


def test_the_subject_agrees_with_the_hand_written_catalog() -> None:
    """Pin the enumeration against an independently maintained object.

    ``loop_registrations.py`` is hand-written, one builder per loop, and is
    kept honest by ``tests/scenarios/catalog/test_catalog_completeness.py``
    against ``orchestrator.bg_loop_registry``. A loop that fell out of
    ``extract_loops`` — the shrinking-subject failure — is still named by its
    builder here, so the two disagreeing is the alarm.
    """
    from_extractor = set(LOOP_CLASS_NAMES)
    from_catalog = set(builder_reachable_classes())

    assert from_extractor == from_catalog, (
        "The loop enumeration and the MockWorld catalog disagree.\n"
        f"  in extract_loops but no builder: {sorted(from_extractor - from_catalog)}\n"
        f"  built by the catalog but not enumerated: "
        f"{sorted(from_catalog - from_extractor)}\n\n"
        "The second list is the dangerous one: a loop the extractor stopped "
        "seeing is a loop this gate stopped asking about, while the gate "
        "stays green."
    )
    assert len(catalog_builder_keys()) >= _MIN_LOOPS, (
        f"Only {len(catalog_builder_keys())} catalog keys registered "
        f"(floor {_MIN_LOOPS}) — loop_registrations failed to import fully, so "
        "the pin above compares two shrunken sets and agrees by accident."
    )
