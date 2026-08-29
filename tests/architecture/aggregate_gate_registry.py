"""Registry of gates whose SUBJECT is a whole tree, and how CI triggers them.

The rule this registry exists to keep true (#11730):

    **A gate's trigger scope must be at least as wide as its subject scope.**

An *aggregate* gate measures a quantity summed over many files — a parametrize
count across all of ``tests/``, a suppression count across all of ``src/`` —
and compares it to a committed mark. CI decides whether to RUN such a gate from
a ``dorny/paths-filter`` allowlist. When the filter is narrower than the tree
the gate measures, a change inside the subject but outside the trigger moves
the number **without any gate seeing it**. The breach then lands on the base
branch and reddens the next unrelated PR, which is how #11730 was found:
``origin/staging`` sat at ``parametrize copies 413 > baseline 412`` and blocked
every open PR, misattributed to whoever pushed next.

The hole is not simply "the ``arch`` filter is narrow". ``tests/architecture``
is run by TWO lanes — the ``arch`` job (filter ``arch``) and the ``test`` job
(``pytest tests/``, filter ``core_python``) — so the effective trigger for an
``tests/architecture`` gate is the union of both. The real hole is what that
union still misses: ``core_python`` carries ``predicate-quantifier: every`` with
``!tests/regressions/**``, ``!tests/scenarios/**`` and
``!tests/sandbox_scenarios/**``, and no other lane that collects
``tests/architecture`` restores them. A PR touching only
``tests/regressions/**`` therefore runs ``Regression Tests``
(``pytest tests/regressions/``) and nothing that reads the whole-``tests/``
aggregates.

Two fixes, and this registry drives the first:

* **Trigger scope (this registry).** ``AGGREGATE_GATES`` names the gates that
  run in the UNGATED ``aggregate-ratchets`` CI job. Ungated means no
  paths-filter can shrink the trigger below the subject, whatever the subject
  is — including subjects no path glob could ever express, like git history.
* **Base scope.** The same job runs on ``push`` to ``main``/``staging``, so a
  breach assembled from individually-green PRs is measured against the real
  merged tree within minutes of landing rather than never.

Three buckets, and every ratchet-shaped gate must be in exactly one, so a new
one forces a decision instead of defaulting into the hole:

``AGGREGATE_GATES``
    Subject is a whole tree; runs in the ungated lane. Trigger ⊇ subject by
    construction.
``TRIGGER_COVERS_SUBJECT``
    Subject is a whole tree, but an existing filter already covers it. The
    reason names the filter, so the claim is checkable rather than assumed.
``DEFERRED_MISMATCHES``
    Known mismatch, not closed here, each with the reason it was not. Capped by
    ``DEFERRED_MISMATCHES_MAX`` and shrink-only: an entry may leave, none may
    join without moving the cap in a reviewed change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

#: Name of the ungated CI job that runs :data:`AGGREGATE_GATES`.
LANE_JOB = "aggregate-ratchets"

#: The ``make`` target that job invokes, so local and CI runs are the same run.
LANE_MAKE_TARGET = "aggregate-ratchets"

#: Makefile variable holding the lane's pytest paths.
LANE_MAKE_VARIABLE = "AGGREGATE_RATCHET_PATHS"


@dataclass(frozen=True)
class AggregateGate:
    """One gate, its subject tree, and the evidence that it still measures it."""

    #: Repo-relative path of the test module that enforces the gate.
    test_path: str
    #: Human description of what quantity is summed and against what mark.
    subject: str
    #: Roots the gate reads. ``"<git-history>"`` for subjects no glob can express.
    subject_roots: tuple[str, ...]
    #: Substring that must appear in ``test_path``'s source, proving the subject
    #: claim above is still true. If a gate is re-pointed at a different tree,
    #: this anchor stops matching and the registry must be revisited — the same
    #: device ``test_arch_check_trigger_coverage.py`` uses to tie required
    #: input roots back to evidence in the generator source.
    evidence: str


#: Gates that run in the ungated ``aggregate-ratchets`` lane.
AGGREGATE_GATES: tuple[AggregateGate, ...] = (
    AggregateGate(
        test_path="tests/architecture/test_suite_hygiene_ratchet.py",
        subject=(
            "parametrize copies + cross-file duplicate tests summed over every "
            "pytest-collected module under tests/, vs "
            "disturbance/baselines/suite_hygiene.yaml"
        ),
        subject_roots=("tests",),
        evidence='collect_tests(real_repo_root / "tests")',
    ),
    AggregateGate(
        test_path="tests/architecture/test_no_ignored_active_tests.py",
        subject=(
            "skip/xfail/commented-out coverage across every .py under tests/ "
            "(no allowance — the count must stay at zero)"
        ),
        subject_roots=("tests",),
        evidence='TESTS_ROOT.rglob("*.py")',
    ),
    AggregateGate(
        test_path="tests/architecture/test_adr0023_test_local_class_instantiation.py",
        subject="dead test-local classes across every test module under tests/",
        subject_roots=("tests",),
        evidence='_dead_test_local_classes(real_repo_root / "tests")',
    ),
    AggregateGate(
        test_path="tests/architecture/test_duration_ratchet.py",
        subject=(
            "every entry of the shrink-only _SLOW_TEST_GRANDFATHER set must "
            "still resolve to a real test node, anywhere under tests/"
        ),
        subject_roots=("tests",),
        evidence="conftest._SLOW_TEST_GRANDFATHER",
    ),
    AggregateGate(
        test_path="tests/test_disturbance_ratchet.py",
        subject=(
            "the disturbance dampener's three dimensions: suppressions "
            "(# noqa / # type: ignore over src/**/*.py), mock_spec (bare mocks "
            "over tests/**/test_*.py) and traceability (untraced fraction over "
            "recent merge history, recomputed where history is available and "
            "marker-only on a shallow clone), each vs disturbance/baselines/*.yaml"
        ),
        subject_roots=("src", "tests", "<git-history>"),
        evidence="run_gate(REPO_ROOT)",
    ),
)


#: Aggregate gates whose existing trigger already covers their subject. The
#: reason must name the filter that does the covering, so this is a checkable
#: claim rather than an assumption. Keys are repo-relative test paths.
TRIGGER_COVERS_SUBJECT: dict[str, str] = {
    "tests/architecture/test_mass_ratchet.py": (
        "subject is src/**/*.py (erosion.mass.collect_sources). The `arch` "
        "filter covers src/arch/**; `core_python` covers the rest of "
        "src/**/*.py and runs tests/architecture via `pytest tests/`. Union "
        "of the two lanes ⊇ subject."
    ),
    "tests/architecture/test_concentration_ratchet.py": (
        "subject is the src/**/*.py file-level import graph. Same lane union "
        "as the mass ratchet above covers it."
    ),
    "tests/architecture/test_adr_enforcement_ratchet.py": (
        "subject is docs/adr/*.md (Accepted ADRs) plus the checks that resolve "
        "them. The `arch` filter lists docs/adr/** explicitly, and arch-regen "
        "adds docs/standards/**."
    ),
    "tests/architecture/test_audit_src_layout_ratchet.py": (
        "subject is scripts/hydraflow_audit/**/*.py. `core_python` includes "
        "scripts/** with no negation over it."
    ),
}


#: Known mismatches this change does not close, each with the reason. Shrink-only.
DEFERRED_MISMATCHES: dict[str, str] = {
    "tests/test_no_screenshot_regression_tests.py": (
        "Subject is the whole repo (tests/, src/ui/, .github/); trigger is "
        "`core_python`, which negates tests/{architecture,regressions,"
        "scenarios,sandbox_scenarios}/** and never covers .github/**. NOT "
        "moved into the lane yet because its main assertion is parametrized "
        "over files discovered at COLLECTION time — an empty or mis-rooted "
        "scan yields zero parameters and a green run. Moving a gate that can "
        "pass vacuously into a lane whose whole purpose is that a run which "
        "measures nothing must fail would launder the vacuity, so it needs its "
        "own anti-vacuity assertion first."
    ),
    "tests/test_prompt_fitness.py": (
        "Subject is every prompt builder discovered across src/**/*.py "
        "(prompt_fitness._src_root().rglob). Trigger is `core_python`, which "
        "negates !src/arch/**. Narrow hole (a *_prompt builder added under "
        "src/arch/) and closing it means moving a heavier suite into the "
        "ungated lane; left for a follow-up that can weigh that cost."
    ),
    "tests/test_prompt_registry_completeness.py": (
        "Same subject and same src/arch/** hole as test_prompt_fitness.py, "
        "and the same reason for deferring."
    ),
    "tests/test_adr_enforcement_completeness.py": (
        "Subject is docs/adr/*.md against fixed caps (_PROSE_ONLY_MAX, "
        "_MISSING_MAX, _UNATTRIBUTED_MAX). Trigger is `core_python`, which "
        "does not list docs/adr/** at all; the `arch` job does list it but "
        "runs only tests/architecture, which this file is not in. Closing it "
        "properly means moving the file under tests/architecture/ — a "
        "relocation with its own review surface, not a trigger change."
    ),
    "tests/test_adr_conformance_coverage.py": (
        "Same subject (docs/adr/*.md) and the same trigger hole as "
        "test_adr_enforcement_completeness.py above; same reason for deferring."
    ),
}

#: Ratchet, shrink-only: the deferred list may lose entries, never gain them
#: without a reviewed move of this number. Set to the count at introduction
#: (#11730) so the inventory cannot quietly grow.
DEFERRED_MISMATCHES_MAX = 5


def lane_test_paths() -> tuple[str, ...]:
    """Repo-relative pytest paths for the ungated lane, in registry order."""
    return tuple(gate.test_path for gate in AGGREGATE_GATES)


def repo_root() -> Path:
    """Repository root — two levels up from ``tests/architecture/``."""
    return Path(__file__).resolve().parents[2]


def makefile_lane_paths() -> tuple[str, ...]:
    """The lane as the MAKEFILE spells it — the second of the two copies.

    Deliberately a separate object from :func:`lane_test_paths`. The Makefile
    is what actually runs, in CI and locally; this module is what explains and
    guards it. Two objects that must agree is the only arrangement in which
    losing one is visible at all (``docs/standards/parametrised_guards``), and
    it is what lets a drop from ``AGGREGATE_GATES`` be *detected* rather than
    merely regretted: the equality is asserted in
    ``test_aggregate_gate_trigger_scope.py``, and the drop-detector registered
    in ``guard_enumeration_registry.py`` reads this side of it.
    """
    match = re.search(
        rf"^{re.escape(LANE_MAKE_VARIABLE)}\s*[:?]?=\s*(.*)$",
        (repo_root() / "Makefile").read_text(encoding="utf-8"),
        re.M,
    )
    assert match, (
        f"could not find `{LANE_MAKE_VARIABLE}` in the Makefile — the lane is "
        "parsed from there, so a rename must update this reader rather than "
        "silently resolving to nothing"
    )
    return tuple(match.group(1).split())
