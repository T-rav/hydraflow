"""Regression test for issue #9176 — ADR-0011 drifts on unrelated core-module churn.

Bug (filed by ``adr_touchpoint_auditor`` per ADR-0056):
    ADR-0011 *Epic Release Creation Architecture* was flagged as "drifted"
    across 7 PRs (#9108, #9127, #9130, #9135, #9148, #9151, #9161) because each
    PR's diff touched one of the modules ADR-0011 cites — ``src/models.py``,
    ``src/epic.py``, ``src/pr_manager.py`` — without ADR-0011's own file being
    in the diff.

Root cause:
    ADR-0011's ``Related`` section cites those three modules at *file*
    granularity (bare ``` `src/models.py` ``` etc., with no ``:Symbol`` tail).
    ``adr_index.parse_adr_file`` records bare citations with an *empty* symbol
    set, and the drift path (``ADRIndex.adrs_touching`` → ``adr_drift.compute_drift``)
    keys purely on ``ADR.source_files`` — it never consults ``source_symbols``.
    So *any* change to these three extremely high-churn shared modules drifts
    ADR-0011, even when the change has nothing to do with epic-release creation
    (the 7 reported PRs are dashboard/viz hardening, factory-process refinements,
    a dependabot fix, and an RC merge — none touch the release path).

    The same coarse-citation pattern flags ~17 ADRs on these same RC PRs, so this
    is a systemic false-positive: ADR-0011 can never stabilise because the modules
    it claims at file granularity change on essentially every RC.

Expected behaviour after fix (repair option 1 in the issue — "update the ADR"):
    ADR-0011 should stop drifting on changes that don't touch the
    epic-release-creation behaviour it documents. Concretely, narrowing its
    ``Related`` citations so the auditor no longer treats whole high-churn
    shared modules as ADR-0011's responsibility means an unrelated PR touching
    ``src/models.py`` / ``src/pr_manager.py`` / ``src/epic.py`` no longer
    produces an ADR-0011 drift rollup.

These tests assert that fixed state, so they are RED until ADR-0011 is repaired.
They drive the real ``docs/adr`` directory and the production drift logic — no
stubs — so a green result genuinely means the drift no longer reproduces.

Self-retiring: if ADR-0011 is removed, renumbered, or made non-Accepted, it
drops out of the drift computation and these assertions pass without a false
failure.
"""

from __future__ import annotations

from pathlib import Path

from adr_drift import compute_drift_by_adr
from adr_index import ADRIndex

_ADR_DIR = Path(__file__).resolve().parents[2] / "docs" / "adr"

# The 7 PRs exactly as listed in issue #9176, paired with the ADR-0011-cited
# module each one's diff touched. None of these PRs changed
# ``docs/adr/0011-*.md`` (that is why the auditor flagged drift), and none of
# them altered the epic-release-creation path ADR-0011 documents:
#   #9108  WS-RT real-time visualization hardening   -> src/models.py
#   #9127  factory-process refinement (triage)       -> src/models.py
#   #9130  factory-process refinement (impl)         -> src/models.py
#   #9135  factory-process refinement                -> src/models.py
#   #9148  background-task delegation cleanup        -> src/epic.py
#   #9151  s09 dependabot scenario fix               -> src/pr_manager.py
#   #9161  rc/2026-06-03-0314 promotion merge        -> src/pr_manager.py
_REPORTED_PR_DIFFS: list[tuple[int, list[str]]] = [
    (9108, ["src/models.py"]),
    (9127, ["src/models.py"]),
    (9130, ["src/models.py"]),
    (9135, ["src/models.py"]),
    (9148, ["src/epic.py"]),
    (9151, ["src/pr_manager.py"]),
    (9161, ["src/pr_manager.py"]),
]


def _adr_0011_rollup(pr_diffs: list[tuple[int, list[str]]]):
    """Return the ADR-0011 rollup entry from the real drift logic, or None."""
    index = ADRIndex(_ADR_DIR)
    rollups = compute_drift_by_adr(index, pr_diffs)
    return next((r for r in rollups if r.adr.number == 11), None)


def test_unrelated_change_to_cited_core_module_does_not_drift_adr_0011() -> None:
    """A lone PR touching only ``src/models.py`` (unrelated to releases) must not
    flag ADR-0011.

    PR #9108 was visualization-only hardening — it has nothing to do with epic
    release creation — yet ADR-0011's bare ``src/models.py`` citation drifts it.
    """
    rollup = _adr_0011_rollup([(9108, ["src/models.py"])])

    assert rollup is None, (
        "ADR-0011 drifted on PR #9108, which only touched src/models.py for "
        "visualization hardening — unrelated to epic-release creation. "
        "Bare file-level citation of a high-churn shared module is too coarse."
    )


def test_seven_reported_prs_do_not_produce_adr_0011_rollup() -> None:
    """Faithful reproduction of issue #9176: none of the 7 reported PRs should
    produce an ADR-0011 drift rollup once the ADR's citations are narrowed."""
    rollup = _adr_0011_rollup(_REPORTED_PR_DIFFS)

    flagged_prs = list(rollup.pr_numbers) if rollup is not None else []
    assert rollup is None, (
        "ADR-0011 still drifts across the reported PRs "
        f"{flagged_prs} — none of which touch the epic-release-creation path it "
        "documents. Expected no ADR-0011 rollup after repair."
    )
