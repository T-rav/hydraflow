"""Guard: every issue-filing background loop must carry a per-tick filing cap.

Regression for #10777. ``WikiRotDetectorLoop`` filed one ``hydraflow-find``
issue per broken cite with no per-tick cap and flooded the board (~7 issues in
a tick) before #10767 added a :class:`filing_budget.FilingBudget`. #10777 turns
that one-off fix into an invariant over EVERY loop that files GitHub issues:

    A ``src/*_loop.py`` that calls ``PRPort.create_issue`` must either
      (a) carry a per-tick filing cap — a ``*_max_issues_per_tick`` /
          ``*_max_issues_per_run`` / ``*_max_corpus_cases`` config field, or the
          shared ``FilingBudget`` gate — OR
      (b) be provably bounded by design and listed in ``_PROVABLY_BOUNDED``
          with a one-line reason it cannot flood.

A NEW filing loop that is neither capped nor allowlisted trips this test, so the
footgun cannot silently recur. ``_GRANDFATHERED_UNCAPPED`` holds the loops known
to be uncapped at #10777 that were not fixed in that PR; it is a ratchet that
MUST shrink toward empty and MUST NOT grow — capping one of them (which makes it
carry a marker) trips :func:`test_grandfathered_loops_stay_uncapped_until_removed`
so it gets removed from the list rather than lingering.

The check is a deliberately conservative source-text scan, mirroring the
``tests/_credit_reraise_audit.py`` ratchet: "files issues" == the source calls
``.create_issue(``; "has a cap" == the source mentions a cap marker. Both
over-approximate toward safety — a loop that merely *mentions* a cap marker is
trusted, and a loop that reaches ``create_issue`` only through a cross-module
callback is invisible. Prefer allowlisting a false positive to loosening the
scan.
"""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src"

# The single canonical issue-creation Port method (``ports.py`` / ``pr_manager``);
# a loop that files issues per tick calls it directly or via a ``_file_*`` helper.
_CREATE_ISSUE_CALL = ".create_issue("

# A loop carries a per-tick filing cap if its source references one of these:
#   - ``<loop>_max_issues_per_tick`` / ``<loop>_max_issues_per_run`` config field,
#   - ``<loop>_max_corpus_cases`` (a corpus-sampling cap that bounds filings), or
#   - the shared ``FilingBudget`` gate (``src/filing_budget.py``).
_CAP_MARKERS = (
    "max_issues_per_tick",
    "max_issues_per_run",
    "max_corpus_cases",
    "FilingBudget",
)

# Loops that call ``create_issue`` but are bounded by DESIGN — they file at most
# a small fixed number of issues per tick regardless of board/repo/finding
# volume — so they need no cap. Each entry documents WHY it cannot flood. This
# list is permanent (unlike the ratchet below); a loop leaves it only if its
# filing shape changes.
_PROVABLY_BOUNDED: dict[str, str] = {
    "branch_protection_auditor_loop.py": "single create_issue, no loop; deduped on one drift report",
    "ci_monitor_loop.py": "single create_issue guarded by the _open_issue once-flag",
    "cost_budget_watcher_loop.py": "single create_issue on a fixed title, deduped",
    "diagram_loop.py": "single create_issue; all unassigned items folded into one body",
    "fail_open_monitor_loop.py": "files at most the one latest breach day, deduped by fingerprint",
    "fake_coverage_auditor_loop.py": "iterates the fixed Fake* class roster; rolled into one body per (fake,kind)",
    "gate_activator_loop.py": "single create_issue; all proposals folded into one body, deduped",
    "health_monitor_loop.py": "iterates the fixed background-loop registry; per-site dedup + restart-first",
    "issue_refinement_loop.py": "single rolling digest issue, create-once dedup",
    "live_corpus_replay_loop.py": "at most 2 rolling issues (drift rollup + escalation), never a per-finding loop",
    "pricing_refresh_loop.py": "at most one issue/tick (parse OR bounds), violations folded into one body",
    "rails_drift_caretaker_loop.py": "iterates the fixed 3-class finding taxonomy (missing-layer/coverage-floor/missing-gate-script) per repo, each deduped by (repo, finding_class)",
    "rc_budget_loop.py": "signals are a subset of {median, spike}, so <=2 create_issue/tick",
    "report_issue_loop.py": "processes exactly one peeked report per tick; budget sweep is one deduped call",
    "retrospective_loop.py": "bounded by the fixed review-category taxonomy, per-category dedup",
    "second_order_vitals_loop.py": "at most one alarm, filed only on the transition into diverging",
    "staging_bisect_loop.py": "one red SHA processed per tick; mutually-exclusive filing branches",
    "staging_promotion_loop.py": "one promotion PR per tick; rolling issue + streak escalation, both deduped",
    "trust_fleet_sanity_loop.py": "bounded by fixed fleet topology x anomaly kinds, per-anomaly dedup",
}

# Ratchet: loops KNOWN to file per-finding with no per-tick cap as of #10777 that
# were not fixed in that PR (multi-site budget threading / create-vs-update split
# / attempt-gated non-dedup filing make the summary-shape fix non-trivial). This
# set MUST shrink toward empty and MUST NOT grow — a new uncapped loop must be
# fixed or provably-bounded, never added here. When one of these gains a cap it
# is removed (enforced below), not left to linger.
_GRANDFATHERED_UNCAPPED: frozenset[str] = frozenset(
    {
        "adr_conformance_loop.py",
        "corpus_learning_loop.py",
        "flake_tracker_loop.py",
    }
)


def _iter_loop_files() -> list[Path]:
    return sorted(_SRC.glob("*_loop.py"))


def _is_filing_loop(path: Path) -> bool:
    return _CREATE_ISSUE_CALL in path.read_text(encoding="utf-8")


def _iter_filing_loops() -> list[Path]:
    return [p for p in _iter_loop_files() if _is_filing_loop(p)]


def _has_cap(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    return any(marker in text for marker in _CAP_MARKERS)


def test_every_filing_loop_is_capped_or_provably_bounded() -> None:
    """No filing loop may be uncapped unless it is documented-bounded/grandfathered."""
    offenders: list[str] = []
    for path in _iter_filing_loops():
        name = path.name
        if _has_cap(path):
            continue
        if name in _PROVABLY_BOUNDED:
            continue
        if name in _GRANDFATHERED_UNCAPPED:
            continue
        offenders.append(name)

    assert not offenders, (
        "These loops call PRPort.create_issue but carry no per-tick filing cap "
        f"and are not on an allowlist: {sorted(offenders)}. A loop that files "
        "one issue per finding floods the board when a burst surfaces at once "
        "(#10767/#10777). Fix by adding a `<loop>_max_issues_per_tick` config "
        "field gated through `filing_budget.FilingBudget` (file ONE summary "
        "issue on overflow where a DedupStore backs idempotency, or defer "
        "over-cap findings to the next tick). If the loop is bounded by design "
        "(files at most a small fixed number per tick), add it to "
        "`_PROVABLY_BOUNDED` with a one-line reason instead."
    )


def test_provably_bounded_allowlist_has_no_stale_entries() -> None:
    """Every allowlisted loop must still exist and still be a filing loop."""
    filing = {p.name for p in _iter_filing_loops()}
    stale = sorted(set(_PROVABLY_BOUNDED) - filing)
    assert not stale, (
        f"{stale} are on `_PROVABLY_BOUNDED` but no longer call create_issue "
        "(or no longer exist). Remove them so the allowlist stays honest."
    )


def test_grandfathered_loops_stay_uncapped_until_removed() -> None:
    """Ratchet-down: a grandfathered loop that gains a cap must leave the list."""
    filing = {p.name for p in _iter_filing_loops()}
    stale = sorted(_GRANDFATHERED_UNCAPPED - filing)
    assert not stale, (
        f"{stale} are grandfathered but no longer call create_issue. Remove "
        "them from `_GRANDFATHERED_UNCAPPED`."
    )
    now_capped = sorted(
        name for name in _GRANDFATHERED_UNCAPPED if _has_cap(_SRC / name)
    )
    assert not now_capped, (
        f"{now_capped} now carry a per-tick filing cap — remove them from "
        "`_GRANDFATHERED_UNCAPPED`. The ratchet must shrink toward empty."
    )


def test_bounded_and_grandfathered_lists_are_disjoint() -> None:
    overlap = sorted(set(_PROVABLY_BOUNDED) & _GRANDFATHERED_UNCAPPED)
    assert not overlap, (
        f"{overlap} are in both `_PROVABLY_BOUNDED` and "
        "`_GRANDFATHERED_UNCAPPED`; a loop is one or the other."
    )


def test_audit_finds_the_known_filing_loop_population() -> None:
    """Sanity floor: the scan must still see the filing-loop fleet (not 0)."""
    filing = {p.name for p in _iter_filing_loops()}
    # WikiRotDetectorLoop is the #10767 exemplar and must always be captured.
    assert "wiki_rot_detector_loop.py" in filing
    assert len(filing) >= 30, (
        f"only {len(filing)} filing loops detected — the create_issue scan may "
        "have regressed; expected the full ~34-loop fleet."
    )
