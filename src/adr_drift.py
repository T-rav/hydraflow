"""Pure citation-intersection logic for `AdrTouchpointAuditorLoop` (ADR-0056).

Given an ADR index and a PR's file diff, returns a list of `DriftFinding`s
— one per Accepted/Proposed ADR whose cited `src/` modules changed without
the ADR's own markdown file being part of the same diff.

For per-ADR rollups (#8987) ``compute_drift_by_adr`` aggregates per-PR
findings across a batch of merged PRs, producing one entry per drifted
ADR with the union of contributing PRs.

For cross-cutting fleet PRs (#9662) ``partition_fleet_drift`` splits the
same input into per-ADR rollups plus one ``FleetDriftBatch`` per PR that
drifts at least ``fleet_threshold`` distinct ADRs — so a fleet-wide
implementation sweep yields ONE batched issue instead of N per-ADR ones.

Kept pure (no I/O, no `gh` calls) so the loop can drive it from real
state and tests can drive it from stubbed inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from adr_index import ADR, ADRIndex


@dataclass(frozen=True)
class DriftFinding:
    """One PR×ADR pair where cited modules changed without the ADR being updated."""

    adr: ADR
    pr_number: int
    changed_cited_files: tuple[str, ...]


def _adr_file_in_diff(adr: ADR, changed_files: Iterable[str]) -> bool:
    """True iff the ADR's own markdown file appears in the diff.

    ADR file paths follow `docs/adr/<NNNN>-<slug>.md` — we match on the
    zero-padded number prefix to tolerate slug renames.
    """
    prefix = f"docs/adr/{adr.number:04d}-"
    return any(f.startswith(prefix) for f in changed_files)


def _split_path_symbol(entry: str) -> tuple[str, str | None]:
    """Split a changed-file entry into ``(path, symbol)``.

    A diff entry may optionally carry a ``:Symbol`` tail mirroring an ADR
    citation (``src/foo.py:Bar.baz``).  In production the auditor passes
    bare file paths — ``gh`` gives file-level diffs, not symbol-level — so
    ``symbol`` is ``None`` for those, which is exactly what makes a
    symbol-qualified citation *not* drift on a file-only touch (#9176).
    """
    path, sep, symbol = entry.partition(":")
    if sep and symbol:
        return path, symbol
    return entry, None


# High-churn modules bare-cited (file-granular) as a *dependency pointer* by
# their pattern ADRs — "the implementation lives here", not "this exact decision
# is this file". A file-level touch is implementation churn, not a semantic
# change to any one ADR's decision, so a bare citation is read as a dependency
# mention and does NOT drift. They are the dominant source of ADR-drift false
# positives. An ADR that genuinely *owns* a symbol in one of these must cite it
# at ``:Symbol`` granularity (``src/config.py:HydraFlowConfig``,
# ``src/pr_manager.py:PRManager.upload_screenshot_gist``) to drift.
#
# Lineage:
#   * #9176 suppressed the symbol-cited case.
#   * #9397 added the first four cross-cutting infra modules (config, models,
#     ports, post_merge_handler) for the residual bare-cited case.
#   * pr_manager.py joined as the next-highest-churn dependency.
#   * 2026-06-13: the dashboard/server/repo_runtime startup surface and the
#     contract-testing subsystem (contract_recording/diff/refresh_loop, bare-
#     cited as dependency pointers by ADR-0047/0052) were the remaining recurring
#     "ADR drift unresolved after 3" HITL escalations — added here so normal
#     in-scope churn stops re-firing them.
#   * 2026-07-24 (#10455, epic #10454): the review pipeline (review_advisor,
#     review_phase/_phase) and the base_background_loop base class — bare-cited
#     as dependency pointers by many review/loop ADRs — were the current
#     high-churn gap (~15 FPs across #10388/#10405/#10406, plus the
#     base_background_loop FP class #10441/#10443). The systemic churn-derived
#     replacement for this hand-maintained allowlist landed in #10456 — see
#     :func:`_bare_citation_fanout` and the ``fanout_threshold`` path in
#     :func:`_citation_drifts`, which suppress a bare citation once enough
#     live ADRs bare-cite the same module, no hand-edit required. The two
#     paths are OR'd: this allowlist still applies independently.
_SHARED_INFRA_MODULES = frozenset(
    {
        "src/config.py",
        "src/models.py",
        "src/ports.py",
        "src/post_merge_handler.py",
        "src/pr_manager.py",
        # Dashboard / server / multi-repo startup surface — cross-cutting,
        # bare-cited as a dependency by the dashboard + multi-repo ADRs
        # (0007/0008/0013/0019/0038/0050/0060/0090).
        "src/dashboard.py",
        "src/server.py",
        "src/repo_runtime.py",
        # Contract-testing subsystem — bare-cited as dependency pointers by
        # ADR-0047 (the pattern) and ADR-0052; cassettes/recorders evolve on
        # normal contract churn that does not change either decision.
        "src/contract_recording.py",
        "src/contract_diff.py",
        "src/contract_refresh_loop.py",
        # Review pipeline + base-loop dependency-pointer citations — high-churn
        # implementation surface many review/loop ADRs bare-cite; the current
        # dominant FP source (#10388/#10405/#10406, base-loop #10441/#10443).
        "src/review_advisor.py",
        "src/review_phase/_phase.py",
        "src/base_background_loop.py",
    }
)


def _bare_citation_fanout(path: str, adrs: Iterable[ADR]) -> int:
    """Count how many of *adrs* cite *path* bare (empty cited-symbol set).

    A symbol-qualified citation for the same file doesn't count — only a
    bare citation is subject to the any-touch-drifts rule this fan-out
    gates, so only bare citations should count toward the threshold. This
    is the churn signal behind the derived shared-infra suppression
    (#10456): a ``src/`` module that many live ADRs bare-cite is, by that
    fan-out alone, a dependency pointer rather than any one ADR's decision.
    """
    return sum(1 for adr in adrs if not adr.source_symbols.get(path, frozenset()))


def _is_shared_infra(
    path: str,
    *,
    fanout: int = 0,
    fanout_threshold: int | None = None,
) -> bool:
    """Single source of truth: is a *bare* citation to *path* treated as a
    high-churn shared-infra dependency pointer?

    True when either the manual :data:`_SHARED_INFRA_MODULES` allowlist names
    *path*, or (once #10456 threads a threshold) *path* is bare-cited by at
    least *fanout_threshold* live ADRs. The two conditions are OR'd, matching
    :func:`_citation_drifts`. ``fanout_threshold=None`` disables the derived
    branch, leaving only the manual allowlist.

    Both the drift-suppression path (:func:`_citation_drifts`, which does NOT
    drift such a bare citation) and the authoring nudge
    (:func:`bare_infra_citation_nudges`, #10458, which suggests re-citing at
    ``:Symbol`` granularity) route through this one predicate so they can never
    diverge — the nudge fires on exactly the bare citations suppression covers.
    """
    if path in _SHARED_INFRA_MODULES:
        return True
    return fanout_threshold is not None and fanout >= fanout_threshold


def _citation_drifts(
    adr: ADR,
    path: str,
    changed_symbols: frozenset[str],
    *,
    fanout: int = 0,
    fanout_threshold: int | None = None,
) -> bool:
    """Decide whether *path* drifts *adr* given the symbols changed in it.

    Symbol-aware (#9176):

    * **Bare-file citation** (empty cited-symbol set) → drifts on *any*
      touch of the file.  This preserves the legacy file-granular
      behaviour the P2 gate and the existing drift tests rely on — except
      for the cross-cutting :data:`_SHARED_INFRA_MODULES`, where a bare
      citation is treated as a dependency mention and does *not* drift
      (it must be cited at ``:Symbol`` granularity to drift). A bare
      citation is *also* suppressed when *path* is bare-cited by at least
      *fanout_threshold* live ADRs (#10456) — a churn-derived equivalent
      of the manual allowlist that self-derives suppression for the next
      high-churn shared module without a hand-edit. The two paths are
      OR'd: either the allowlist OR the fan-out threshold suppresses.
      ``fanout_threshold=None`` disables the derived suppression, leaving
      only the manual allowlist (byte-identical prior behaviour).
    * **Symbol-qualified citation** (non-empty cited-symbol set) → drifts
      only when a symbol the diff reports as changed for this file
      matches one of the cited symbols.  A file-only diff (no symbol
      evidence) therefore does *not* drift a symbol-granular citation, so
      unrelated churn in a high-churn shared module no longer flags the
      ADR — the systemic false positive behind #9176. Fan-out is
      irrelevant here: a genuinely symbol-owning ADR still drifts
      regardless of how many *other* ADRs bare-cite the same file.
    """
    cited_symbols = adr.source_symbols.get(path, frozenset())
    if not cited_symbols:
        return not _is_shared_infra(
            path, fanout=fanout, fanout_threshold=fanout_threshold
        )
    return bool(cited_symbols & changed_symbols)


@dataclass(frozen=True)
class CitationNudge:
    """A non-blocking authoring nudge (#10458).

    ADR *adr_number* bare-cites *path*, a high-churn shared-infra module, so
    the citation is *silently suppressed* from drift detection (it is read as
    a dependency pointer, not a decision anchor — see
    :func:`_is_shared_infra`). If the ADR genuinely owns a specific symbol
    there, re-citing it at *suggestion* granularity (``path:Symbol``) restores
    drift on real changes to that symbol without re-flagging unrelated churn.

    Pure authoring aid: it changes no drift-detection behaviour and is never a
    CI gate — it is surfaced only as a soft section in the generated ADR
    cross-reference report.
    """

    adr_number: int
    path: str
    suggestion: str


def bare_infra_citation_nudges(
    adrs: Iterable[ADR],
    *,
    shared_infra_fanout_threshold: int | None = None,
) -> list[CitationNudge]:
    """Flag every bare citation of a shared-infra module for a ``:Symbol`` nudge.

    Returns one :class:`CitationNudge` per ``(ADR, path)`` pair where the ADR
    bare-cites (empty cited-symbol set) a ``src/`` module that
    :func:`_is_shared_infra` treats as a dependency pointer — i.e. exactly the
    bare citations :func:`_citation_drifts` suppresses. Nudge and suppression
    share the one :func:`_is_shared_infra` predicate, so #10456's churn-derived
    set flows to both without either drifting from the other.

    ``shared_infra_fanout_threshold`` mirrors :func:`compute_drift`: when
    given, a ``src/`` path bare-cited by at least that many of *adrs* is also
    nudged (churn-derived), on top of the manual allowlist. ``None`` (the
    default — the offline generator has no config) restricts nudges to the
    manual :data:`_SHARED_INFRA_MODULES` set, which is correct, just narrower.

    Output is sorted by ``(adr_number, path)`` for deterministic rendering.
    """
    adr_list = list(adrs)
    nudges: list[CitationNudge] = []
    for adr in adr_list:
        for path, cited_symbols in adr.source_symbols.items():
            # Symbol-qualified citations already drift correctly — leave them.
            if cited_symbols:
                continue
            # The shared-infra rule (allowlist + fan-out) is scoped to ``src/``
            # modules, matching ``compute_drift``'s ``src_paths`` filter.
            if not path.startswith("src/"):
                continue
            fanout = _bare_citation_fanout(path, adr_list)
            if not _is_shared_infra(
                path,
                fanout=fanout,
                fanout_threshold=shared_infra_fanout_threshold,
            ):
                continue
            nudges.append(
                CitationNudge(
                    adr_number=adr.number,
                    path=path,
                    suggestion=f"{path}:<Symbol>",
                )
            )
    nudges.sort(key=lambda n: (n.adr_number, n.path))
    return nudges


def compute_drift(
    adr_index: ADRIndex,
    pr_number: int,
    changed_files: Iterable[str],
    *,
    shared_infra_fanout_threshold: int | None = None,
) -> list[DriftFinding]:
    """Return drift findings for one PR's file diff.

    Drift is symbol-aware (#9176): an ADR that cites a file at *symbol*
    granularity (``src/foo.py:Bar``) only drifts when the diff reports a
    change to that symbol; a bare ``src/foo.py`` citation still drifts on
    any change to the file.  ``changed_files`` entries may optionally carry
    a ``:Symbol`` tail to supply symbol evidence; bare paths — the
    production case — supply none.

    ``shared_infra_fanout_threshold`` (#10456): when given, a ``src/`` path
    bare-cited by at least this many live (Accepted/Proposed) ADRs is
    treated as shared infra — the same suppression as
    :data:`_SHARED_INFRA_MODULES` but derived from citation fan-out instead
    of a hand-maintained list. ``None`` (the default) disables this derived
    suppression, preserving prior behaviour exactly.

    Findings are sorted by ADR number for deterministic output.
    """
    files = list(changed_files)
    # Collapse optional `:Symbol` tails into a path → changed-symbols map.
    changed_by_path: dict[str, set[str]] = {}
    for entry in files:
        path, symbol = _split_path_symbol(entry)
        bucket = changed_by_path.setdefault(path, set())
        if symbol:
            bucket.add(symbol)
    src_paths = [p for p in changed_by_path if p.startswith("src/")]
    if not src_paths:
        return []
    by_path = adr_index.adrs_touching(src_paths)

    adr_hits: dict[int, tuple[ADR, list[str]]] = {}
    for path, adrs in by_path.items():
        changed_symbols = frozenset(changed_by_path.get(path, set()))
        fanout = _bare_citation_fanout(path, adrs)
        for adr in adrs:
            if not _citation_drifts(
                adr,
                path,
                changed_symbols,
                fanout=fanout,
                fanout_threshold=shared_infra_fanout_threshold,
            ):
                continue
            slot = adr_hits.setdefault(adr.number, (adr, []))
            slot[1].append(path)

    findings: list[DriftFinding] = []
    for number in sorted(adr_hits):
        adr, paths = adr_hits[number]
        if _adr_file_in_diff(adr, files):
            continue
        findings.append(
            DriftFinding(
                adr=adr,
                pr_number=pr_number,
                changed_cited_files=tuple(sorted(paths)),
            )
        )
    return findings


@dataclass(frozen=True)
class AdrRollupEntry:
    """All PRs that drifted a given ADR in one scan batch (#8987).

    Used by ``AdrTouchpointAuditorLoop`` to file/update one rollup issue
    per ADR instead of one issue per ``(PR, ADR)`` tuple.
    """

    adr: ADR
    contributors: tuple[DriftFinding, ...]

    @property
    def pr_numbers(self) -> tuple[int, ...]:
        return tuple(sorted({f.pr_number for f in self.contributors}))


def _aggregate_by_adr(findings: Iterable[DriftFinding]) -> list[AdrRollupEntry]:
    """Group already-computed drift findings into one entry per drifted ADR.

    Single source of truth for the grouping/sorting semantics shared by
    :func:`compute_drift_by_adr` and :func:`partition_fleet_drift`: findings
    keep their input order within each ADR's contributor tuple, and output
    is sorted by ADR number for deterministic processing.
    """
    per_adr: dict[int, tuple[ADR, list[DriftFinding]]] = {}
    for finding in findings:
        slot = per_adr.setdefault(finding.adr.number, (finding.adr, []))
        slot[1].append(finding)

    return [
        AdrRollupEntry(adr=adr, contributors=tuple(entry_findings))
        for _, (adr, entry_findings) in sorted(per_adr.items())
    ]


def compute_drift_by_adr(
    adr_index: ADRIndex,
    pr_diffs: Iterable[tuple[int, Iterable[str]]],
    *,
    shared_infra_fanout_threshold: int | None = None,
) -> list[AdrRollupEntry]:
    """Group per-PR drift findings into one rollup entry per drifted ADR.

    ``pr_diffs`` is an iterable of ``(pr_number, changed_files)`` tuples
    — typically the PRs returned by one ``gh pr list`` page. Output is
    sorted by ADR number for deterministic processing.

    A PR whose diff includes the ADR's own file is silently skipped for
    that ADR — drift on that pair is considered resolved by the same PR
    (matches ``compute_drift``'s per-PR semantics).

    ``shared_infra_fanout_threshold`` is threaded straight through to each
    :func:`compute_drift` call — see its docstring (#10456).
    """
    return _aggregate_by_adr(
        finding
        for pr_number, changed_files in pr_diffs
        for finding in compute_drift(
            adr_index,
            pr_number,
            changed_files,
            shared_infra_fanout_threshold=shared_infra_fanout_threshold,
        )
    )


@dataclass(frozen=True)
class FleetDriftBatch:
    """All ADRs drifted by one cross-cutting fleet PR (#9662).

    Produced by :func:`partition_fleet_drift` when a single PR drifts at
    least ``fleet_threshold`` distinct ADRs. The loop files ONE batched
    ``hydraflow-adr-drift`` issue for the whole batch (dedup key
    ``adr_touchpoint_auditor:FLEET-<pr>``) instead of N per-ADR rollups.

    ``entries`` carries one single-contributor :class:`AdrRollupEntry` per
    drifted ADR, sorted by ADR number.
    """

    pr_number: int
    entries: tuple[AdrRollupEntry, ...]

    @property
    def adr_numbers(self) -> tuple[int, ...]:
        return tuple(e.adr.number for e in self.entries)


def partition_fleet_drift(
    adr_index: ADRIndex,
    pr_diffs: Iterable[tuple[int, Iterable[str]]],
    *,
    fleet_threshold: int,
    shared_infra_fanout_threshold: int | None = None,
) -> tuple[list[AdrRollupEntry], list[FleetDriftBatch]]:
    """Split drift findings into per-ADR rollups + per-PR fleet batches (#9662).

    A PR drifting ``>= fleet_threshold`` distinct ADRs becomes exactly one
    :class:`FleetDriftBatch`; its findings are REMOVED from the per-ADR
    aggregation so the same drift is never double-filed (the core
    correctness invariant). Every other PR's findings aggregate per-ADR
    exactly as :func:`compute_drift_by_adr` would — below-threshold drift
    keeps the existing per-ADR rollup shape unchanged.

    ``compute_drift``'s per-PR self-coverage carries over: an ADR whose own
    file is in the PR's diff contributes no finding and does not count
    toward the threshold. Batches are sorted by PR number; entries within a
    batch by ADR number (deterministic output).

    ``shared_infra_fanout_threshold`` is threaded straight through to each
    :func:`compute_drift` call — see its docstring (#10456).
    """
    if fleet_threshold < 2:
        raise ValueError(
            f"fleet_threshold must be >= 2, got {fleet_threshold} — a lower "
            "value would batch ordinary single-ADR drift"
        )
    per_adr_findings: list[DriftFinding] = []
    batches: list[FleetDriftBatch] = []
    for pr_number, changed_files in pr_diffs:
        findings = compute_drift(
            adr_index,
            pr_number,
            changed_files,
            shared_infra_fanout_threshold=shared_infra_fanout_threshold,
        )
        # ``compute_drift`` emits at most one finding per ADR, sorted by ADR
        # number — so ``len(findings)`` IS the distinct-ADR count.
        if len(findings) >= fleet_threshold:
            batches.append(
                FleetDriftBatch(
                    pr_number=pr_number,
                    entries=tuple(
                        AdrRollupEntry(adr=f.adr, contributors=(f,)) for f in findings
                    ),
                )
            )
        else:
            per_adr_findings.extend(findings)
    batches.sort(key=lambda b: b.pr_number)
    return _aggregate_by_adr(per_adr_findings), batches
