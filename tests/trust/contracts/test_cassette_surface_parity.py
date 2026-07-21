"""Reciprocal cassette↔dispatcher surface-parity guard (#9440).

The GitHub contract corpus already has a **one-directional** guard: every
cassette must have a dispatcher branch, else ``_invoke_fake_github`` (and
its FakeGit/FakeDocker siblings) raise ``NotImplementedError`` at replay.
There is no synchronous guard in the other direction — that the fake's
whole *adapter surface* is cassetted. Today that gap is caught only weekly,
by ``FakeCoverageAuditorLoop`` (spec §4.7), which files a rollup issue when
a fake exposes a public adapter-surface method with no matching cassette.

This module turns that weekly caretaker signal into a **synchronous CI
gate** for all three cassette-capable fakes (github / git / docker, the
``_FAKE_TO_CASSETTE_DIR`` scope, ADR-0047). It reuses the auditor's *own*
catalog primitives — with the *same argument shapes* the loop uses
(``catalog_fake_methods(fake_dir, repo_root=...)``) — so a surface method
that would make the loop file a rollup next week instead reddens a unit
test at PR time.

Shrink-only per-fake baseline
-----------------------------
Only FakeGitHub carries un-cassetted surface today (58 methods); FakeGit
and FakeDocker are already fully covered (issues #9181 / #9177 closed those
gaps). ``GRANDFATHERED_UNCASSETTED`` seeds the *current* gap per fake so the
guard is green on the current tree, then ratchets: a **new** uncovered
surface method (not in the baseline) reddens
``test_adapter_surface_fully_cassetted``, and a baseline entry that gained a
cassette (or left the surface) reddens
``test_grandfathered_baseline_only_shrinks`` until it is pruned. The
baseline may only shrink — do NOT grow it to silence a new gap; record the
cassette instead. Mirrors ``tests/architecture/test_sandbox_seam_completeness.py``
and ``tests/test_disturbance_ratchet.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fake_coverage_auditor_loop import (
    _FAKE_TO_CASSETTE_DIR,
    catalog_cassette_methods,
    catalog_fake_methods,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FAKE_DIR = _REPO_ROOT / "src" / "mockworld" / "fakes"
_CASSETTE_ROOT = _REPO_ROOT / "tests" / "trust" / "contracts" / "cassettes"

# Un-cassetted adapter-surface methods grandfathered per fake so the guard is
# green on the current tree. This is the honest, current coverage gap — the
# weekly ``FakeCoverageAuditorLoop`` would file a rollup for exactly these.
# SHRINK ONLY: record a cassette (and prune the entry here) to close a gap.
# A NEW uncovered method must be cassetted, NOT added below. All three audited
# fakes (FakeGitHub, FakeGit, FakeDocker) are fully cassetted today, hence the
# empty baselines — the adapter-surface audit is at zero uncovered methods.
GRANDFATHERED_UNCASSETTED: dict[str, frozenset[str]] = {
    # FakeGitHub is now FULLY cassetted (#9768 closed by slice 5 — the final
    # workflow-run / CI-log / git-op / alerts cluster). All three audited fakes
    # have empty baselines; the FakeCoverageAuditorLoop adapter-surface audit is
    # at zero uncovered methods.
    "FakeGitHub": frozenset(),
    "FakeDocker": frozenset(),
    "FakeGit": frozenset(),
}

# The fakes under audit — the cassette-capable scope. Sorted for stable
# parametrize IDs (``test_...[FakeDocker]`` / ``[FakeGit]`` / ``[FakeGitHub]``).
_FAKES = sorted(_FAKE_TO_CASSETTE_DIR)


def _surface_and_cassetted(fake: str) -> tuple[set[str], set[str]]:
    """Adapter surface and cassetted method sets for ``fake``.

    Uses the SAME argument shape ``FakeCoverageAuditorLoop._do_work`` uses:
    ``catalog_fake_methods(fake_dir, repo_root=repo)`` (so FakeGitHub's
    in-memory scaffolding — ``add_issue`` / ``from_seed`` / ``seed_*`` — is
    split out against the real PRManager/PRPort surface, not mis-counted as
    an un-cassetted adapter method), and ``catalog_cassette_methods`` over
    the fake's ``_FAKE_TO_CASSETTE_DIR`` sub-directory.
    """
    catalog = catalog_fake_methods(_FAKE_DIR, repo_root=_REPO_ROOT)
    surface = set(catalog.get(fake, {}).get("adapter-surface", []))
    cassetted = catalog_cassette_methods(_CASSETTE_ROOT / _FAKE_TO_CASSETTE_DIR[fake])
    return surface, cassetted


@pytest.mark.parametrize("fake", _FAKES)
def test_adapter_surface_fully_cassetted(fake: str) -> None:
    """Every adapter-surface method of ``fake`` is cassetted (modulo baseline).

    Synchronous stand-in for the weekly ``FakeCoverageAuditorLoop``
    adapter-surface audit: ``surface - cassetted - grandfathered == {}``.
    """
    surface, cassetted = _surface_and_cassetted(fake)
    grandfathered = GRANDFATHERED_UNCASSETTED.get(fake, frozenset())
    missing = surface - cassetted - grandfathered
    assert missing == set(), (
        f"{fake} exposes adapter-surface methods with no matching cassette "
        f"under tests/trust/contracts/cassettes/{_FAKE_TO_CASSETTE_DIR[fake]}/: "
        f"{sorted(missing)}. Record a cassette whose input.command names each "
        f"method (and add a dispatcher branch to the fake's _invoke_* helper). "
        f"Do NOT add them to GRANDFATHERED_UNCASSETTED — the baseline only shrinks."
    )


@pytest.mark.parametrize("fake", _FAKES)
def test_grandfathered_baseline_only_shrinks(fake: str) -> None:
    """No baseline entry is stale — the ratchet can only shrink.

    A grandfathered method that gained a cassette (or left the surface —
    renamed, deleted, or reclassified as helper/scaffolding) is no longer an
    uncovered surface method and MUST be pruned in the same change.
    """
    surface, cassetted = _surface_and_cassetted(fake)
    grandfathered = GRANDFATHERED_UNCASSETTED.get(fake, frozenset())
    uncovered = surface - cassetted
    stale = grandfathered - uncovered
    assert stale == set(), (
        f"{fake}: GRANDFATHERED_UNCASSETTED lists methods that are no longer "
        f"uncovered surface methods (now cassetted or off-surface): "
        f"{sorted(stale)}. Prune them from GRANDFATHERED_UNCASSETTED in this "
        f"change so the baseline stays honest."
    )


@pytest.mark.parametrize("fake", _FAKES)
def test_surface_is_non_empty(fake: str) -> None:
    """Anti-vacuity canary.

    If ``catalog_fake_methods`` regresses (rename, glob typo, scaffolding
    misclassification) and returns an empty surface, the parity assertion
    above would pass vacuously. Every cassette-capable fake has at least one
    adapter-surface method, so pin that.
    """
    surface, _cassetted = _surface_and_cassetted(fake)
    assert surface, (
        f"{fake} has an empty adapter surface — catalog_fake_methods likely "
        f"regressed; the parity guard would pass vacuously."
    )


def test_baseline_keys_are_audited_fakes() -> None:
    """GRANDFATHERED_UNCASSETTED may only key fakes actually under audit.

    A typo'd or stale fake key would seed a baseline that no parametrized
    case ever consumes, silently hiding a real gap under a near-miss name.
    """
    stale_keys = set(GRANDFATHERED_UNCASSETTED) - set(_FAKE_TO_CASSETTE_DIR)
    assert stale_keys == set(), (
        f"GRANDFATHERED_UNCASSETTED keys not in _FAKE_TO_CASSETTE_DIR: "
        f"{sorted(stale_keys)}. Rename or prune them."
    )
