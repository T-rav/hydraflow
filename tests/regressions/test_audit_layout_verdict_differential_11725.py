"""The audit's verdict must not depend on which ``src`` layout a repo uses (#11725).

Two gates already hold the #11709 class, and both have a measured blind spot:

* the **static ratchet** (``tests/architecture/test_audit_src_layout_ratchet.py``)
  asserts the literal ``src`` has exactly one owner. It scans ``*.py`` under
  ``scripts/hydraflow_audit/`` and nothing else, so a flat path built in an
  out-of-package helper — ``src/false_close.py``, which ``checks/p10_tdd.py``
  imports ``UI_TEST_RE`` from — or held in a non-``.py`` data file is invisible
  to it;
* the **registry sweep** (``test_audit_packaged_src_layout_11709.py``) runs every
  registered check against a packaged fixture and asserts none exits at a path
  probe. Its real condition is narrower than that sentence: the flat path must
  *also* surface as a ``src/<path> missing``-shaped message. A flat path that
  degrades a check into a **wrong verdict** walks straight past it.

Measured by planting each defect in the tree and running all three gates
(#11725's table, reproduced on this branch's base with the differential added):

===========================================================  =======  =====  ==========================
plant                                                        ratchet  sweep  this differential
===========================================================  =======  =====  ==========================
``UI_TEST_RE`` reverted to flat, in ``src/false_close.py``    green    green  P10.6 (PASS, WARN)
``_fake_dirs`` flat-only via ``ctx.src_root().joinpath(…)``   green    green  P3.3, P3.13, P3.14
``ctx.src_root() / "ports.py"`` in P2.2                       green    RED    P2.2, P2.2a
===========================================================  =======  =====  ==========================

Why this gate is shaped as a differential
------------------------------------------
The tempting fix — widen the static scan to ``src/`` too — is the same disease
one level up. Enumerating scopes drifts exactly the way enumerating spellings
did (five evasion rounds in #11717), ``src/`` is ~340 modules where flat paths
are often legitimate (``scripts/impacted_tests.HIGH_FANOUT_SRC``), and no text
scan of any scope can see a path held in a data file.

So this reads no source text at all. It builds **the same repo in both
layouts**, runs the **whole registry** against each, and asserts per-check
status equality. That is immune to spelling, to scope, and to file type at
once, and a check added tomorrow is covered without anyone listing it.

Its power is bounded by what the fixture exercises, so the fixture is
git-backed with a UI-only ``fix(ui): …`` branch — that is what puts P10.6 in
reach, the one check whose layout blindness *blocks* a PR rather than merely
misreporting. ``_EXEMPT`` is empty and was measured empty: all 98 registered
checks already agree.

Refs #11673 (the class), #11709 / #11717 (the instance), #6855 (a gate that
was never added).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from scripts.hydraflow_audit import checks as _all_checks  # noqa: F401
from scripts.hydraflow_audit import context, registry
from scripts.hydraflow_audit.checks import p10_tdd
from scripts.hydraflow_audit.checks._helpers import finding
from scripts.hydraflow_audit.models import CheckContext, Finding, Status
from scripts.hydraflow_audit.registry import CheckFn

from tests.regressions._audit_layout_fixtures import (
    CONFORMANT,
    FLAT,
    PKG,
    flat_rel,
    materialize,
    probe_exit_findings,
    ui_fix_branch,
)

#: The PR-context switch P10.6 reads. Without it P10.6 is NA in both layouts —
#: agreeing for the wrong reason — which is why every test here sets it.
_PR_BASE_ENV = "HYDRAFLOW_AUDIT_PR_BASE"

#: Checks permitted to return a different verdict per layout.
#:
#: Empty, and measured empty rather than hoped empty: the prototype ran all 98
#: registered checks against both fixtures and found zero disagreements. A new
#: entry here is not a tuning knob — it is a check whose verdict depends on how
#: the repo spells its source directory, which is #11709 by definition. Fix the
#: check.
_EXEMPT: frozenset[str] = frozenset()

#: Floor on the comparison's subject. A differential over an empty registry
#: agrees perfectly and proves nothing (#6855). What fills the registry is the
#: ``checks`` package import above — every ``@register`` decorator fires on it
#: — so this floor is also what keeps that import from being quietly dropped.
_MIN_COMPARED_CHECKS = 90


def _build_pair(base: Path) -> tuple[Path, Path]:
    """The same repo twice: flat ``src/x.py`` and packaged ``src/<pkg>/x.py``."""
    flat = ui_fix_branch(materialize(base / "flat", FLAT), "src/ui")
    packaged = ui_fix_branch(
        materialize(base / "packaged", CONFORMANT), f"src/{PKG}/ui"
    )
    return flat, packaged


@pytest.fixture(scope="module")
def layout_pair(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """``(flat_root, packaged_root)`` — built once, never mutated by a test."""
    return _build_pair(tmp_path_factory.mktemp("src_layout_differential"))


def _verdicts(root: Path) -> dict[str, Status]:
    """Every registered check's status against *root*, keyed by check id."""
    ctx = context.build(root)
    return {
        check_id: fn(ctx).status
        for check_id, fn in sorted(registry.all_registered().items())
    }


def _disagreements(pair: tuple[Path, Path]) -> dict[str, tuple[Status, Status]]:
    """``{check_id: (flat_status, packaged_status)}`` for every check that differs."""
    flat, packaged = (_verdicts(root) for root in pair)
    return {
        check_id: (flat[check_id], packaged[check_id])
        for check_id in flat
        if flat[check_id] is not packaged[check_id]
    }


@contextmanager
def _planted(check_id: str, fn: CheckFn) -> Iterator[None]:
    """Register *fn* for the duration of the block, then restore the registry."""
    snapshot = registry._snapshot_for_tests()
    try:
        registry.register(check_id)(fn)
        yield
    finally:
        registry._restore_for_tests(snapshot)


# --- the invariant --------------------------------------------------------


def test_no_check_changes_its_verdict_with_the_src_layout(
    layout_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One assertion for the whole #11709 class, with no source text involved."""
    monkeypatch.setenv(_PR_BASE_ENV, "main")

    offenders = {
        check_id: (flat.value, packaged.value)
        for check_id, (flat, packaged) in _disagreements(layout_pair).items()
        if check_id not in _EXEMPT
    }

    assert offenders == {}, (
        "These checks answer differently depending on how the repo spells its "
        f"source directory (flat, packaged): {offenders}. The two fixtures are "
        "the same repo — only the layout differs — so a verdict difference is "
        "#11709: a flat path resolving somewhere the packaged repo does not "
        "have. Resolve modules with ctx.src_module(...) / ctx.src_dir(...), "
        "directories with ctx.src_dir(...), and diff-path prefixes with "
        "src_candidates(...). ctx.src_root() is a RECURSIVE scan root; "
        "appending a filename to it rebuilds the bug."
    )


def test_the_exemption_list_is_empty() -> None:
    """It started empty because it was measured, and it is shrink-only."""
    assert not _EXEMPT, (
        "A check exempted from the layout differential is a check whose verdict "
        f"depends on the src layout: {sorted(_EXEMPT)}. That is #11709, not a "
        "property to grandfather."
    )
    assert not (_EXEMPT - set(registry.all_registered())), (
        "Exemptions naming checks that are not registered — stale entries make "
        "the list look busier than it is."
    )


# --- the differential has a subject ---------------------------------------


def test_the_differential_compares_the_whole_registry(
    layout_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard the guard: zero compared checks agree perfectly and prove nothing."""
    monkeypatch.setenv(_PR_BASE_ENV, "main")
    flat_root, packaged_root = layout_pair

    flat, packaged = _verdicts(flat_root), _verdicts(packaged_root)

    assert len(flat) >= _MIN_COMPARED_CHECKS, (
        f"only {len(flat)} checks registered — the differential would pass with "
        "almost nothing to compare. Import the check modules."
    )
    assert flat.keys() == packaged.keys(), (
        "the two runs saw different registries, so the headline test would "
        "compare whichever check ids happened to overlap"
    )


def test_the_pair_really_is_two_layouts_of_one_repo(
    layout_pair: tuple[Path, Path],
) -> None:
    """Guard the guard: two copies of the SAME layout agree for free.

    Both halves are asserted on disk, not inferred from the spec, because the
    failure this protects against is a builder that silently produced one
    layout twice — after which the headline test passes forever.
    """
    flat_root, packaged_root = layout_pair

    assert (flat_root / "src" / "ports.py").is_file()
    assert not (flat_root / "src" / PKG).exists()
    assert context.build(flat_root).src_packages == ()

    assert (packaged_root / "src" / PKG / "ports.py").is_file()
    assert not (packaged_root / "src" / "ports.py").exists()
    assert context.build(packaged_root).src_packages == (PKG,)


def test_the_flat_spec_is_the_packaged_spec_with_the_package_segment_removed() -> None:
    """The fixtures are one spec and a transform, never two hand-kept dicts.

    A differential over two trees that have drifted apart reports disagreements
    nobody caused, collects exemptions to quiet them, and stops meaning
    anything.
    """
    packaged_files = {
        rel: body for rel, body in CONFORMANT.items() if rel != f"src/{PKG}/__init__.py"
    }

    assert {flat_rel(rel): body for rel, body in packaged_files.items()} == FLAT
    assert [rel for rel in FLAT if rel.startswith(f"src/{PKG}/")] == []


def test_p10_6_is_inside_the_differentials_reach(
    layout_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The git-backed fixture is load-bearing, so pin that it still bites.

    P10.6 is NA on a tree with no repository and NA off a PR context. Two NAs
    agree, so the headline test would stay green while the only check whose
    layout blindness *blocks* a PR sat outside the comparison entirely — the
    exact way the flat ``UI_TEST_RE`` survived to be found by a review pass.
    """
    monkeypatch.setenv(_PR_BASE_ENV, "main")
    flat_root, packaged_root = layout_pair

    verdicts = (_verdicts(flat_root)["P10.6"], _verdicts(packaged_root)["P10.6"])

    assert verdicts == (Status.PASS, Status.PASS), (
        f"P10.6 returned {[v.value for v in verdicts]} — it must reach its real "
        "UI-only-fix assessment in both layouts, not sit at NA where a layout "
        "regression would be invisible."
    )


# --- guard the guard: each measured blind spot, planted --------------------
#
# One case per row of the table in the module docstring. Rows 1 and 2 are the
# ones the registry sweep scores 0 on; if this file ever catches only row 3, it
# has been rebuilt into the sweep.


def test_it_catches_a_flat_prefix_held_outside_the_audit_package(
    layout_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 1: ``UI_TEST_RE`` reverted to flat in ``src/false_close.py``.

    ``checks/p10_tdd.py`` imports that regex from outside its own package, so
    the static ratchet never opens the file, and P10.6's degraded answer is a
    WARN with no path in it, so the sweep has nothing to match. This is the
    real #11717 defect, and it was caught by a human, not a gate.
    """
    monkeypatch.setenv(_PR_BASE_ENV, "main")
    monkeypatch.setattr(p10_tdd, "_UI_TEST_RE", re.compile(r"^src/ui/.*"))

    offenders = _disagreements(layout_pair)

    assert offenders.get("P10.6") == (Status.PASS, Status.WARN), (
        "the differential no longer sees a flat UI-test prefix reached through "
        f"an out-of-package import — got {offenders}"
    )


def test_it_catches_a_flat_directory_probe_that_only_changes_the_verdict(
    layout_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 2: a flat probe whose failure message names no path at all.

    ``_fake_dirs`` is this shape — the checks built on it (P3.3, P3.13, P3.14)
    report *scenario fakes are missing*, not *this path is missing*. The
    planted check below asserts both halves in one place: the registry sweep
    sees nothing, and this differential sees it.
    """
    monkeypatch.setenv(_PR_BASE_ENV, "main")
    flat_root, packaged_root = layout_pair

    def _flat_fakes_probe(ctx: CheckContext) -> Finding:
        fakes = ctx.src_root().joinpath("mockworld", "fakes")
        if not fakes.is_dir():
            return finding("ZZ.2", Status.FAIL, "no scenario fakes")
        return finding("ZZ.2", Status.PASS, "scenario fakes present")

    with _planted("ZZ.2", _flat_fakes_probe):
        offenders = _disagreements(layout_pair)
        blind_spot = (
            probe_exit_findings(flat_root),
            probe_exit_findings(packaged_root),
        )

    assert offenders.get("ZZ.2") == (Status.PASS, Status.FAIL), (
        f"the differential missed a flat directory probe — got {offenders}"
    )
    assert blind_spot == ({}, {}), (
        "this case is only worth its lines while the registry sweep is blind to "
        f"it; the sweep now reports {blind_spot}, so pick a fresh blind spot "
        "rather than deleting the assertion"
    )


def test_it_catches_a_flat_module_probe_built_from_the_vocabulary(
    layout_pair: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 3: ``ctx.src_root() / "ports.py"`` — no ``src`` literal in the source.

    The sweep catches this one too (it surfaces as ``src/… missing``). Kept so
    a regression that narrowed the differential to messages, rather than
    statuses, still reddens somewhere.
    """
    monkeypatch.setenv(_PR_BASE_ENV, "main")

    def _flat_module_probe(ctx: CheckContext) -> Finding:
        probe = ctx.src_root() / "ports.py"
        if not probe.is_file():
            return finding("ZZ.3", Status.FAIL, f"{ctx.rel(probe)} missing")
        return finding("ZZ.3", Status.PASS, ctx.rel(probe))

    with _planted("ZZ.3", _flat_module_probe):
        offenders = _disagreements(layout_pair)

    assert offenders.get("ZZ.3") == (Status.PASS, Status.FAIL), (
        f"the differential missed a flat module probe — got {offenders}"
    )
