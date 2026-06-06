"""Regression reproduction for issue #9177 — FakeDocker adapter-surface gap.

Issue #9177 is a `fake_coverage_auditor` rollup (#8986): the auditor reports
that ``FakeDocker`` exposes public methods classified as **adapter-surface**
with no matching cassette under ``tests/trust/contracts/cassettes/docker/``:

  * ``clear_fault``
  * ``fail_next``

These are single-shot fault-injection helpers — they have no real-adapter
counterpart (the real container runner has no ``fail_next``/``clear_fault``
method), which is exactly why no cassette can record them. ``FakeGitHub``'s
analogous fault helpers (``clear_rate_limit`` / ``set_rate_limit_mode``) are
already carved out as ``test-helper`` via ``_FAKE_HELPER_OVERRIDES`` in
``fake_coverage_auditor_loop`` — the FakeDocker pair is not, so the auditor
mis-files them as an un-cassetted adapter surface.

This test reproduces the auditor's finding using the auditor's *own* logic:
it catalogs ``FakeDocker``'s adapter-surface methods and the recorded docker
cassettes, then asserts every adapter-surface method has cassette coverage.

It is RED today because ``clear_fault`` and ``fail_next`` are flagged as
adapter-surface yet have no cassette. The test goes GREEN once the gap is
closed by *either* supported repair:

  1. Recording a cassette for each method (the issue's literal repair), OR
  2. Reclassifying them as ``test-helper`` via ``_FAKE_HELPER_OVERRIDES``
     (the FakeGitHub-style carve-out).

Both repairs empty the uncovered set, so this assertion tracks the real gap
rather than one particular fix.

NOTE: this is a *reproduction*, not a fix. Do not edit ``src/`` to make it
pass — the fix belongs to whoever resolves #9177.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import (
    _FAKE_TO_CASSETTE_DIR,
    catalog_cassette_methods,
    catalog_fake_methods,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FAKE = "FakeDocker"


def test_issue_9177_fake_docker_adapter_surface_is_cassetted() -> None:
    """Every ``FakeDocker`` adapter-surface method must have a docker cassette.

    RED for issue #9177: ``clear_fault`` and ``fail_next`` are classified as
    adapter-surface but no cassette under
    ``tests/trust/contracts/cassettes/docker/`` records them.
    """
    fake_dir = _REPO_ROOT / "src" / "mockworld" / "fakes"
    catalog = catalog_fake_methods(fake_dir)
    assert _FAKE in catalog, f"{_FAKE} not found by catalog_fake_methods"

    surface = catalog[_FAKE]["adapter-surface"]

    cassette_dir = (
        _REPO_ROOT
        / "tests"
        / "trust"
        / "contracts"
        / "cassettes"
        / _FAKE_TO_CASSETTE_DIR[_FAKE]
    )
    cassetted = catalog_cassette_methods(cassette_dir)

    uncovered = sorted(method for method in surface if method not in cassetted)

    assert not uncovered, (
        f"{_FAKE} adapter-surface methods with no matching cassette "
        f"(issue #9177): {uncovered}. Repair by recording a cassette for each, "
        f"or reclassify them as test-helpers via _FAKE_HELPER_OVERRIDES."
    )
