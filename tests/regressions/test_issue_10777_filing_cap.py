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

from tests.loop_module_scan import loop_text, loop_units

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
    "branch_protection_auditor_loop": "single create_issue, no loop; deduped on one drift report",
    "ci_monitor_loop": "single create_issue guarded by the _open_issue once-flag",
    "cost_budget_watcher_loop": "single create_issue on a fixed title, deduped",
    "diagram_loop": "single create_issue; all unassigned items folded into one body",
    "fail_open_monitor_loop": "files at most the one latest breach day, deduped by fingerprint",
    "fake_coverage_auditor_loop": "iterates the fixed Fake* class roster; rolled into one body per (fake,kind)",
    "gate_activator_loop": "single create_issue; all proposals folded into one body, deduped",
    "health_monitor_loop": "iterates the fixed background-loop registry; per-site dedup + restart-first",
    "issue_refinement_loop": "single rolling digest issue, create-once dedup",
    "live_corpus_replay_loop": "at most 2 rolling issues (drift rollup + escalation), never a per-finding loop",
    "pricing_refresh_loop": "at most one issue/tick (parse OR bounds), violations folded into one body",
    "rails_drift_caretaker_loop": "iterates the fixed 3-class finding taxonomy (missing-layer/coverage-floor/missing-gate-script) per repo, each deduped by (repo, finding_class)",
    "rc_budget_loop": "signals are a subset of {median, spike}, so <=2 create_issue/tick",
    "report_issue_loop": "processes exactly one peeked report per tick; budget sweep is one deduped call",
    "retrospective_loop": "bounded by the fixed review-category taxonomy, per-category dedup",
    "second_order_vitals_loop": "at most one alarm, filed only on the transition into diverging",
    "staging_bisect_loop": "one red SHA processed per tick; mutually-exclusive filing branches",
    "staging_promotion_loop": "one promotion PR per tick; rolling issue + streak escalation, both deduped",
    "trust_fleet_sanity_loop": "bounded by fixed fleet topology x anomaly kinds, per-anomaly dedup",
}

# Ratchet: loops KNOWN to file per-finding with no per-tick cap as of #10777 that
# were not fixed in that PR (multi-site budget threading / create-vs-update split
# / attempt-gated non-dedup filing make the summary-shape fix non-trivial). This
# set MUST shrink toward empty and MUST NOT grow — a new uncapped loop must be
# fixed or provably-bounded, never added here. When one of these gains a cap it
# is removed (enforced below), not left to linger.
_GRANDFATHERED_UNCAPPED: frozenset[str] = frozenset(
    {
        "adr_conformance_loop",
        "corpus_learning_loop",
        "flake_tracker_loop",
    }
)


def _iter_loop_files() -> list[Path]:
    """Every background loop, as the unit that identifies it.

    Units, not files: a decomposed loop (``src/foo_loop/``) has its filing
    sites spread across mixins, and a ``*_loop.py`` glob would drop it from
    this audit entirely — the loop would read as "not a filing loop" and its
    ``_PROVABLY_BOUNDED`` entry would go stale.
    """
    return loop_units(_SRC)


def _is_filing_loop(path: Path) -> bool:
    return _CREATE_ISSUE_CALL in loop_text(path)


def _iter_filing_loops() -> list[Path]:
    return [p for p in _iter_loop_files() if _is_filing_loop(p)]


def _unit_for(name: str) -> Path | None:
    """Resolve a loop NAME to its unit, whatever shape that loop has on disk.

    The allowlists are keyed by loop name, and a name is not a path: a
    decomposed loop is a directory, so ``_SRC / name`` is neither its module
    nor its package. Building the path by hand yields something that does not
    exist, and ``loop_text`` on a missing directory returns "" rather than
    raising — which turned the shrink-only half of this ratchet into an
    unconditional pass. Resolve through discovery instead.
    """
    return {unit.stem: unit for unit in _iter_loop_files()}.get(name)


def _has_cap(path: Path) -> bool:
    text = loop_text(path)
    return any(marker in text for marker in _CAP_MARKERS)


def test_every_filing_loop_is_capped_or_provably_bounded() -> None:
    """No filing loop may be uncapped unless it is documented-bounded/grandfathered."""
    offenders: list[str] = []
    for path in _iter_filing_loops():
        name = path.stem
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
    filing = {p.stem for p in _iter_filing_loops()}
    stale = sorted(set(_PROVABLY_BOUNDED) - filing)
    assert not stale, (
        f"{stale} are on `_PROVABLY_BOUNDED` but no longer call create_issue "
        "(or no longer exist). Remove them so the allowlist stays honest."
    )


def test_grandfathered_loops_stay_uncapped_until_removed() -> None:
    """Ratchet-down: a grandfathered loop that gains a cap must leave the list."""
    filing = {p.stem for p in _iter_filing_loops()}
    stale = sorted(_GRANDFATHERED_UNCAPPED - filing)
    assert not stale, (
        f"{stale} are grandfathered but no longer call create_issue. Remove "
        "them from `_GRANDFATHERED_UNCAPPED`."
    )
    units = {name: _unit_for(name) for name in _GRANDFATHERED_UNCAPPED}
    unresolved = sorted(name for name, unit in units.items() if unit is None)
    assert not unresolved, (
        f"{unresolved} are grandfathered but no loop of that name exists — "
        "this check cannot see them and would pass vacuously. Remove the "
        "stale entries, or fix the name."
    )
    now_capped = sorted(
        name for name, unit in units.items() if unit is not None and _has_cap(unit)
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
    filing = {p.stem for p in _iter_filing_loops()}
    # WikiRotDetectorLoop is the #10767 exemplar and must always be captured.
    # health_monitor_loop is the decomposed-package exemplar: it files from a
    # mixin, so a file-glob scan would drop it and this floor would not notice.
    assert "wiki_rot_detector_loop" in filing
    assert "health_monitor_loop" in filing
    assert len(filing) >= 30, (
        f"only {len(filing)} filing loops detected — the create_issue scan may "
        "have regressed; expected the full ~34-loop fleet."
    )
