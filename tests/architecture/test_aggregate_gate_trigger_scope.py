"""Guard: a gate's TRIGGER scope must be at least as wide as its SUBJECT scope.

The defect this closes (#11730): a gate that measures a quantity summed over a
whole tree, but which CI runs only when a ``dorny/paths-filter`` allowlist
fires. A path filter is a subset of the repo by construction, so it can never
be as wide as a whole-tree subject. A change inside the subject but outside the
trigger moves the number with nothing watching, the breach lands on the base
branch, and the next unrelated PR wears the red.

The live hole, precisely: ``core_python`` carries ``predicate-quantifier:
every`` with ``!tests/regressions/**``, ``!tests/scenarios/**`` and
``!tests/sandbox_scenarios/**``. The ``arch`` filter restores
``tests/architecture/**`` but not those three. So a change confined to
``tests/regressions/`` fires ``Regression Tests`` — ``pytest tests/regressions/``
— and no lane that reads the whole-``tests/`` aggregates. It can move the
parametrize count the suite-hygiene ratchet gates on, unmeasured.

The fix is the UNGATED ``aggregate-ratchets`` job, and these assertions keep it
that way. The load-bearing one is ``test_the_lane_job_is_ungated``: the instant
someone gives that job an ``if:``, the subject stops being covered and this
reddens.

Written as properties over
``tests/architecture/aggregate_gate_registry.py`` rather than a hand-checked
list, and the registry is required to CLASSIFY every ratchet-shaped gate in the
repo — so a new one forces a decision instead of defaulting into the hole.

Not registered in ``path_membership_registry`` on purpose: that registry
protects collections used as a *membership predicate about a module*, and its
liveness machinery probes what happens when a named module becomes a package.
These entries name test files, which have no such identity to lose. File
existence is asserted here instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.architecture.aggregate_gate_registry import (
    AGGREGATE_GATES,
    DEFERRED_MISMATCHES,
    DEFERRED_MISMATCHES_MAX,
    LANE_JOB,
    LANE_MAKE_TARGET,
    LANE_MAKE_VARIABLE,
    TRIGGER_COVERS_SUBJECT,
    AggregateGate,
    lane_test_paths,
    makefile_lane_paths,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CI = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_MAKEFILE = _REPO_ROOT / "Makefile"

#: Files swept for classification: anything shaped like a ratchet gate.
_RATCHET_GLOBS = ("tests/architecture/test_*_ratchet.py", "tests/test_*_ratchet.py")


def _ci() -> dict:
    return yaml.safe_load(_CI.read_text(encoding="utf-8"))


def _lane_job() -> dict:
    jobs = _ci()["jobs"]
    assert LANE_JOB in jobs, (
        f"ci.yml has no `{LANE_JOB}:` job. That job IS the fix for #11730 — "
        "the ungated lane whose trigger cannot be narrower than its subject. "
        "Deleting it reopens the hole silently, so it fails here loudly."
    )
    return jobs[LANE_JOB]


def _sweep_ratchet_files() -> set[str]:
    found: set[str] = set()
    for glob in _RATCHET_GLOBS:
        parent, _, pattern = glob.rpartition("/")
        for path in sorted((_REPO_ROOT / parent).glob(pattern)):
            found.add(path.relative_to(_REPO_ROOT).as_posix())
    assert found, (
        f"the ratchet sweep {_RATCHET_GLOBS} matched no files — the parse is "
        "broken and every completeness assertion below would pass vacuously"
    )
    return found


# --------------------------------------------------------------------------
# The registry itself must not be vacuous or rotten
# --------------------------------------------------------------------------


def test_the_registry_is_not_empty() -> None:
    """An empty registry would make every property below pass over nothing."""
    assert AGGREGATE_GATES, "no aggregate gates registered — the guard is inert"
    assert lane_test_paths(), "the lane has no test paths"


@pytest.mark.parametrize("gate", AGGREGATE_GATES, ids=lambda g: g.test_path)
def test_each_registered_gate_exists_and_still_measures_its_subject(
    gate: AggregateGate,
) -> None:
    """The file exists and its source still contains the declared subject anchor.

    Without the anchor this registry would be prose: a gate could be re-pointed
    at a narrower tree while the registry kept claiming the wide one, and the
    lane would keep dutifully running a gate that no longer needs it. Same
    device ``test_arch_check_trigger_coverage.py`` uses to tie required input
    roots to evidence in the generator source.
    """
    path = _REPO_ROOT / gate.test_path
    assert path.exists(), (
        f"registered aggregate gate {gate.test_path} does not exist. If it "
        "moved, re-point the registry; if it is gone, remove the entry — a "
        "registry entry that names nothing protects nothing."
    )
    assert gate.evidence in path.read_text(encoding="utf-8"), (
        f"{gate.test_path} no longer contains {gate.evidence!r}, the evidence "
        f"that it still measures {gate.subject_roots}. Either the gate was "
        "re-pointed at a different subject (update subject_roots AND decide "
        "whether it still belongs in the ungated lane) or the anchor needs "
        "re-spelling."
    )


@pytest.mark.parametrize(
    "test_path", sorted(TRIGGER_COVERS_SUBJECT) + sorted(DEFERRED_MISMATCHES)
)
def test_classified_gates_still_exist(test_path: str) -> None:
    """No dead entries: a reason attached to a deleted file is stale reasoning."""
    assert (_REPO_ROOT / test_path).exists(), (
        f"{test_path} is classified in the aggregate-gate registry but does "
        "not exist. Drop the entry."
    )


def test_no_gate_is_classified_twice() -> None:
    """Exactly one bucket each, so a gate cannot be both covered and deferred."""
    lane = set(lane_test_paths())
    covered = set(TRIGGER_COVERS_SUBJECT)
    deferred = set(DEFERRED_MISMATCHES)
    for left, right, names in (
        (lane, covered, "AGGREGATE_GATES/TRIGGER_COVERS_SUBJECT"),
        (lane, deferred, "AGGREGATE_GATES/DEFERRED_MISMATCHES"),
        (covered, deferred, "TRIGGER_COVERS_SUBJECT/DEFERRED_MISMATCHES"),
    ):
        assert not left & right, f"classified in both {names}: {sorted(left & right)}"


def test_every_ratchet_gate_is_classified() -> None:
    """A new ratchet must declare its trigger story, not inherit the hole.

    Inverted allowlist, same shape as
    ``tests/test_ci_path_filter_completeness.py``: in scope by default, and
    staying out requires a written reason. The failure mode flips from "forgot
    to consider it, silently under-triggered" to "must say which bucket".
    """
    classified = (
        set(lane_test_paths()) | set(TRIGGER_COVERS_SUBJECT) | set(DEFERRED_MISMATCHES)
    )
    unclassified = sorted(_sweep_ratchet_files() - classified)
    assert not unclassified, (
        f"ratchet-shaped gates in no bucket of the aggregate-gate registry: "
        f"{unclassified}. Decide: does its subject exceed its CI trigger? If "
        "yes, add it to AGGREGATE_GATES (the ungated lane) or, with a reason, "
        "to DEFERRED_MISMATCHES. If an existing paths-filter genuinely covers "
        "the whole subject, record that filter in TRIGGER_COVERS_SUBJECT."
    )


def test_deferred_mismatches_only_shrink() -> None:
    """Shrink-only: the known-hole list may lose entries, never quietly gain them."""
    assert len(DEFERRED_MISMATCHES) <= DEFERRED_MISMATCHES_MAX, (
        f"{len(DEFERRED_MISMATCHES)} deferred mismatches > cap "
        f"{DEFERRED_MISMATCHES_MAX}. Close one instead of raising the cap; if "
        "the addition is genuinely reviewed, move the cap in the same change "
        "and say why in the PR."
    )


@pytest.mark.parametrize("test_path", sorted(DEFERRED_MISMATCHES))
def test_every_deferred_mismatch_says_why(test_path: str) -> None:
    """An unexplained deferral is how the next hole hides."""
    reason = DEFERRED_MISMATCHES[test_path].strip()
    assert len(reason) > 60, (
        f"{test_path} is deferred with a reason too thin to act on: {reason!r}. "
        "Say what the subject is, what the trigger is, and why it was not closed."
    )


# --------------------------------------------------------------------------
# The lane: ungated in CI, identical locally, and actually required
# --------------------------------------------------------------------------


def test_the_lane_job_is_ungated() -> None:
    """The whole fix in one assertion (#11730).

    An ``if:`` on this job — of ANY shape, including a paths-filter that looks
    generous today — reintroduces a trigger narrower than the subject. There is
    no glob that means "every tree these gates sum over", so the only correct
    trigger is no trigger.
    """
    job = _lane_job()
    assert "if" not in job, (
        f"the `{LANE_JOB}` job grew an `if:` ({job['if']!r}). That job runs "
        "gates whose subject is a whole tree; any condition on it makes the "
        "trigger narrower than the subject, which is exactly the #11730 "
        "defect. If a lane member no longer needs to be ungated, move it out "
        "of AGGREGATE_GATES — do not gate the lane."
    )


def test_the_lane_job_runs_the_make_target() -> None:
    """CI and a local run must be the same run, per ADR-0082's gate contract."""
    commands = " ".join(
        str(step.get("run", "")) for step in _lane_job().get("steps") or []
    )
    assert f"make {LANE_MAKE_TARGET}" in commands, (
        f"the `{LANE_JOB}` job does not invoke `make {LANE_MAKE_TARGET}`. "
        "Inlining the pytest command instead lets CI and the Makefile drift, "
        "and the Makefile is what the local gate and this guard both read."
    )


def test_the_lane_job_is_required_via_ci_gate() -> None:
    """A lane nothing depends on blocks nothing.

    Branch protection requires the ``CI Gate`` umbrella rather than each
    conditional job (see docs/standards/branch_protection/ADDING-A-GATE.md), so
    membership in its ``needs:`` is what makes this gate binding.
    """
    needs = _ci()["jobs"]["ci-gate"]["needs"]
    assert LANE_JOB in needs, (
        f"`{LANE_JOB}` is missing from ci-gate's needs: {needs}. Without it a "
        "breach reddens a job nobody waits on and merges anyway."
    )


def test_the_makefile_lane_matches_the_registry() -> None:
    """One list, two readers — the Makefile variable and the registry."""
    assert makefile_lane_paths() == lane_test_paths(), (
        f"{LANE_MAKE_VARIABLE} in the Makefile has drifted from "
        "AGGREGATE_GATES. The Makefile is what actually runs; the registry is "
        "what explains and guards it. A gate present in one and not the other "
        "is either unexplained or unrun."
    )


@pytest.mark.parametrize("test_path", lane_test_paths())
def test_no_lane_member_is_excluded_from_the_local_suite(test_path: str) -> None:
    """``make quality`` must keep running the lane members it always ran.

    The lane is an ADDITIONAL trigger, never a relocation. If a member were
    also removed from the main local suite, the ungated CI job would become its
    only reader and a local run would stop catching breaches before push.
    """
    makefile = _MAKEFILE.read_text(encoding="utf-8")
    assert f"--ignore={test_path}" not in makefile, (
        f"{test_path} is --ignore'd by a Makefile pytest lane while also being "
        "an ungated-lane member. Keep it in both: the lane backstops CI, "
        "`make quality` backstops the developer."
    )


# --------------------------------------------------------------------------
# The base-scope half: the lane must also run AFTER a merge
# --------------------------------------------------------------------------


def test_the_lane_runs_post_merge_on_the_protected_branches() -> None:
    """Closes the second mechanism: a breach summed from green PRs (#11730).

    ``strict_required_status_checks_policy`` is false on both rulesets, so a
    PR's checks are evaluated against whatever base it branched from and the
    merged result is never what any PR gate saw. Running this ungated lane on
    ``push`` to the protected branches measures the real tree within minutes of
    a merge, whatever any PR touched or triggered.
    """
    # `on` parses as the YAML boolean True — this is the well-known GitHub
    # Actions/YAML 1.1 collision, not a typo.
    triggers = _ci()[True]
    branches = (triggers.get("push") or {}).get("branches") or []
    assert {"main", "staging"} <= set(branches), (
        f"ci.yml no longer runs on push to main and staging (got {branches}). "
        f"The `{LANE_JOB}` lane is the post-merge aggregate gate; without the "
        "push trigger only PR-time runs remain, and those are evaluated "
        "against a stale base."
    )
