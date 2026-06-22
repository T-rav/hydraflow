"""Regression test for issue #9565 — ADR-0007 cites the deleted ``src/dashboard_routes.py`` monolith.

Bug:
    ADR-0007 *Dashboard API Architecture for Multi-Repo Scoping*
    (``docs/adr/0007-dashboard-api-multi-repo-scoping.md``) lists
    ``src/dashboard_routes.py`` in its ``## Related`` / citation section, but
    that file no longer exists — the monolith was split into the
    ``src/dashboard_routes/`` package (``_routes.py``, ``_control_routes.py``,
    ``_hitl_routes.py``, …).

Root cause / consequence:
    ``adr_index.parse_adr_file`` records the bare ``src/dashboard_routes.py``
    citation in ``ADR.source_files``, and the touchpoint auditor
    (``ADRIndex.adrs_touching`` → ``adr_drift.compute_drift``) matches that
    citation against the *changed file paths* of merged PRs. A citation to a
    path that no longer exists can never appear in any real diff, so ADR-0007
    has effectively **zero touchpoint coverage** for the route layer it
    documents — every change to the actual ``src/dashboard_routes/`` package
    sails past the auditor without ever flagging ADR-0007.

Expected behaviour after fix:
    ADR-0007 must stop citing the non-existent ``src/dashboard_routes.py``
    monolith. The issue leaves the repair open — either drop the stale citation
    or re-point it at the package (a symbol-qualified citation such as
    ``src/dashboard_routes/_routes.py:create_router``, since a bare directory
    citation would re-introduce false positives). The assertion below is
    fix-agnostic: it passes under *either* repair, because both remove the
    dangling ``src/dashboard_routes.py`` path from the ADR's cited source files.

This test drives the real ``docs/adr/0007-*.md`` file through the production
``adr_index`` parser — no stubs — so a green result genuinely means the stale
citation is gone. It is RED until ADR-0007 is repaired.

Note: ADR-0007 also cites ``src/hf_cli/supervisor_service.py`` and
``src/hf_cli/supervisor_client.py``, which are likewise absent from the current
tree. Those are a separate (unfiled) staleness; this test is scoped strictly to
the ``dashboard_routes`` monolith named in issue #9565 so a failure maps
unambiguously to this bug.
"""

from __future__ import annotations

from pathlib import Path

from adr_index import parse_adr_file

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADR_0007 = _REPO_ROOT / "docs" / "adr" / "0007-dashboard-api-multi-repo-scoping.md"
_DELETED_MONOLITH = "src/dashboard_routes.py"


def test_dashboard_routes_monolith_is_gone_and_package_exists() -> None:
    """Precondition: the monolith really was split into a package.

    Documents the ground truth the regression depends on — if this ever flips
    (the monolith returns), the citation would no longer be stale and the
    regression below would no longer apply.
    """
    assert not (_REPO_ROOT / _DELETED_MONOLITH).exists(), (
        "src/dashboard_routes.py unexpectedly exists — the monolith was supposed "
        "to be split into the src/dashboard_routes/ package."
    )
    assert (_REPO_ROOT / "src" / "dashboard_routes").is_dir(), (
        "src/dashboard_routes/ package is missing — repo layout assumption broken."
    )


def test_adr_0007_does_not_cite_nonexistent_dashboard_routes_path() -> None:
    """ADR-0007 must not cite a ``dashboard_routes`` source path that no longer exists.

    Fix-agnostic: any ``src/dashboard_routes*`` path the ADR cites must resolve
    to a real file on disk. The bare monolith citation (``src/dashboard_routes.py``)
    fails this because the file is gone; a re-pointed citation at the package
    (e.g. ``src/dashboard_routes/_routes.py``) or dropping the citation entirely
    both satisfy it.
    """
    adr = parse_adr_file(_ADR_0007)

    dashboard_route_citations = sorted(
        f for f in adr.source_files if "dashboard_routes" in f
    )
    missing = [f for f in dashboard_route_citations if not (_REPO_ROOT / f).exists()]

    assert not missing, (
        "ADR-0007 cites dashboard-route source path(s) that no longer exist: "
        f"{missing}. The monolith src/dashboard_routes.py was split into the "
        "src/dashboard_routes/ package; a citation to a path that no longer "
        "exists never matches any diff, so ADR-0007 has zero touchpoint "
        "coverage for the route layer it documents. Drop the stale citation or "
        "re-point it at the package (issue #9565)."
    )
