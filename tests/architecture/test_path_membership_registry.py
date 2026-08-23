"""Repo-wide properties over every registered path-membership collection.

**Read this before adding a set of module paths anywhere.** If your collection
holds source paths and is consulted with ``in`` / ``fnmatch`` / substring to
decide something about a module, register it in
``tests/architecture/path_membership_registry.py``. Registration is manual and
explicit — a collection nobody registers is a collection nobody protects.

Two properties are asserted here, and between them they would have caught all
eleven known instances of the defect class:

1. **Every anchored entry resolves on disk.** A membership test whose entries
   name nothing looks exactly like a membership test that happens not to match
   this diff. ``src/coordinator.py`` and ``src/persistence/`` both sat in
   merge-gating collections for over three months naming paths that had never
   existed in this repo's history, and the only thing that ever found them was
   somebody adding this assertion.

2. **Membership follows a module into a package.** ``src/review_phase.py``
   became ``src/review_phase/`` on 2026-05-11. Every gate keyed on the literal
   string stopped covering the module that day, silently, and stayed green.
   The property is checked by feeding each collection's LIVE production
   predicate a synthetic package member of its own entry.

Neither property has a grandfather list. Property 1 has none because every
dead entry found by the #11669 sweep was fixable, and a baseline of dead
entries is the same failure one level up: a list nobody re-reads. Property 2
allows a per-collection exemption with a written reason, ratcheted shrink-only
by ``test_package_blind_exemptions_only_shrink``.
"""

from __future__ import annotations

import fnmatch

import pytest

from path_membership import module_identities
from tests.architecture.path_membership_registry import (
    PathMembership,
    classify_entry,
    package_probe_for_entry,
    registered_path_memberships,
    repo_paths,
    repo_root,
)

MEMBERSHIPS: tuple[PathMembership, ...] = registered_path_memberships()

# Shrink-only ratchet. Lower it when you fix a collection; never raise it.
# Raising it means a new gate was allowed to go package-blind on purpose.
PACKAGE_BLIND_EXEMPTIONS_MAX = 1


def _ids(memberships: tuple[PathMembership, ...]) -> list[str]:
    return [m.name for m in memberships]


def _probes_for(membership: PathMembership) -> list[tuple[str, str]]:
    """``(entry, synthetic package member)`` for every probeable entry.

    A collection can legitimately have none — ``audit.stratify``'s marker
    tuples are mostly bare tokens (``gauntlet``, ``secret``) that never
    claimed to name a module. Vacuity is guarded suite-wide by
    :meth:`TestRegistryIsWiredUp.test_the_package_property_probes_real_entries`
    rather than per collection, so an all-fragment collection does not have to
    invent a knob to opt out.
    """
    probes = []
    for entry in membership.entries:
        probe = package_probe_for_entry(entry, membership.match_kind)
        if probe is not None:
            probes.append((entry, probe))
    return probes


# The package-follows-module property must actually probe something. This floor
# is a vacuity guard, not a target: it fails if a refactor quietly stops
# generating probes (e.g. classify_entry changing what counts as a module).
MIN_TOTAL_PACKAGE_PROBES = 20


class TestRegistryIsWiredUp:
    """A rule nobody wires up is the failure mode one level higher."""

    def test_registry_is_not_empty(self) -> None:
        assert MEMBERSHIPS, (
            "registered_path_memberships() returned nothing — every property "
            "below would then pass vacuously, which is exactly the shape of "
            "bug this file exists to catch."
        )

    def test_every_membership_carries_entries_and_a_predicate(self) -> None:
        empty = [m.name for m in MEMBERSHIPS if not m.entries]
        assert not empty, (
            f"registered collections with no entries: {empty}. An empty "
            "collection makes its properties vacuous; unregister it instead."
        )

    def test_the_package_property_probes_real_entries(self) -> None:
        """Suite-wide vacuity guard for the package-follows-module property."""
        enforced = [m for m in MEMBERSHIPS if m.package_blind_reason is None]
        total = sum(len(_probes_for(m)) for m in enforced)
        assert total >= MIN_TOTAL_PACKAGE_PROBES, (
            f"only {total} package probes were generated across "
            f"{len(enforced)} enforced collections, under the floor of "
            f"{MIN_TOTAL_PACKAGE_PROBES}. The property is passing because it "
            "is testing almost nothing — check classify_entry and "
            "package_probe_for_entry before lowering this."
        )

    def test_registered_names_are_unique(self) -> None:
        names = _ids(MEMBERSHIPS)
        assert len(names) == len(set(names)), (
            f"duplicate registry names in {sorted(names)} — a duplicate hides "
            "one of the two collections from the failure message."
        )


class TestEveryEntryResolvesOnDisk:
    """Property 1 — no entry may name something that is not there."""

    @pytest.mark.parametrize("membership", MEMBERSHIPS, ids=_ids(MEMBERSHIPS))
    def test_every_anchored_entry_selects_a_real_path(
        self, membership: PathMembership
    ) -> None:
        """Each repo-anchored entry must select at least one path that exists.

        "Anchored" excludes free-floating fragments like ``secret`` or
        ``schema_evolution``: those are forward-looking needles, and matching
        nothing today is their designed state. Everything that names a
        specific module, tree, or prefix has to be real.
        """
        tracked = repo_paths()
        root = repo_root()
        dead: list[str] = []
        for entry in membership.entries:
            kind = classify_entry(entry)
            if kind == "fragment":
                continue
            if kind == "module":
                # A module resolves as its file OR as the package that file
                # became — the entry keeps naming the MODULE either way.
                target = root / entry
                if target.is_file() or target.with_suffix("").is_dir():
                    continue
                if membership.match_kind == "glob" and any(
                    fnmatch.fnmatch(p, entry) for p in tracked
                ):
                    continue
                dead.append(entry)
            elif kind == "tree":
                if not (root / entry.rstrip("/")).is_dir():
                    dead.append(entry)
            elif not any(
                p.startswith(entry) or fnmatch.fnmatch(p, entry) for p in tracked
            ):
                dead.append(entry)

        assert not dead, (
            f"{membership.name} names paths that do not exist: {dead}.\n"
            f"What this silently stops doing: {membership.why}\n"
            "Fix the entry (repoint it at the module's real location, or "
            "delete it if the module is gone). Do NOT add it to an exemption "
            "list — a dead entry is a gate that stopped firing, and the only "
            "reason it survived this long is that nothing was checking."
        )


class TestMembershipFollowsAModuleIntoAPackage:
    """Property 2 — decomposing a module must not drop it out of its gate."""

    @pytest.mark.parametrize(
        "membership",
        [m for m in MEMBERSHIPS if m.package_blind_reason is None],
        ids=_ids(tuple(m for m in MEMBERSHIPS if m.package_blind_reason is None)),
    )
    def test_a_package_member_of_each_entry_still_matches(
        self, membership: PathMembership
    ) -> None:
        """Feed the live predicate a synthetic member of each entry's package.

        ``src/review_phase.py`` probes ``src/review_phase/_probe.py``;
        ``src/*_loop.py`` probes ``src/probemodule_loop/_probe.py``. A
        predicate that answers ``False`` here is one that will stop covering
        its module the day someone splits it — and will not say so.
        """
        blind = [
            (entry, probe)
            for entry, probe in _probes_for(membership)
            if not membership.matches(probe)
        ]
        assert not blind, (
            f"{membership.name} stops matching when its module becomes a "
            f"package: {blind}.\n"
            f"What this silently stops doing: {membership.why}\n"
            "Match on module IDENTITY: run each candidate path through "
            "path_membership.module_identities() before comparing, the way "
            "review_advisor.is_self_modifying_path and "
            "judge_independence._path_matches do."
        )

    def test_package_blind_exemptions_only_shrink(self) -> None:
        exempt = [m.name for m in MEMBERSHIPS if m.package_blind_reason is not None]
        assert len(exempt) <= PACKAGE_BLIND_EXEMPTIONS_MAX, (
            f"{len(exempt)} collections are exempt from the "
            f"package-follows-module property ({sorted(exempt)}), over the "
            f"ratchet of {PACKAGE_BLIND_EXEMPTIONS_MAX}. This ratchet is "
            "shrink-only: fix a collection and lower it. Raising it declares "
            "that a gate is allowed to silently stop covering its module."
        )

    def test_every_exemption_states_a_reason(self) -> None:
        unexplained = [
            m.name
            for m in MEMBERSHIPS
            if m.package_blind_reason is not None
            and len(m.package_blind_reason.strip()) < 40
        ]
        assert not unexplained, (
            f"package_blind_reason is boilerplate for {unexplained}. The "
            "reason has to say why a decomposition failing to match here is "
            "acceptable — in practice, only that the failure is LOUD."
        )


class TestModuleIdentities:
    """The primitive every registered matcher is built on."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            pytest.param(
                "src/review_phase/_ci.py",
                ("src/review_phase/_ci.py", "src/review_phase.py"),
                id="package-member-yields-its-pre-split-module",
            ),
            pytest.param(
                "src/a/b/c.py",
                ("src/a/b/c.py", "src/a/b.py", "src/a.py"),
                id="nested-packages-walk-every-ancestor",
            ),
            pytest.param(
                "src/review_advisor.py",
                ("src/review_advisor.py",),
                id="flat-module-is-only-itself",
            ),
            pytest.param(
                "tests/regressions/test_x.py",
                ("tests/regressions/test_x.py", "tests/regressions.py"),
                id="stops-before-the-top-level-root",
            ),
        ],
    )
    def test_identities(self, path: str, expected: tuple[str, ...]) -> None:
        assert module_identities(path) == expected

    def test_top_level_root_is_never_an_identity(self) -> None:
        """``src`` is a directory that was never a module.

        Emitting ``src.py`` would let a needle like ``src.py`` match every
        file in the tree, which is the opposite failure to the one this
        module exists to prevent.
        """
        for path in ("src/foo.py", "src/a/b.py", "tests/t.py"):
            assert "src.py" not in module_identities(path)
            assert "tests.py" not in module_identities(path)
