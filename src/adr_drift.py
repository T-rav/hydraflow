"""Pure citation-intersection logic for `AdrTouchpointAuditorLoop` (ADR-0056).

Given an ADR index and a PR's file diff, returns a list of `DriftFinding`s
— one per Accepted/Proposed ADR whose cited `src/` modules changed without
the ADR's own markdown file being part of the same diff.

For per-ADR rollups (#8987) ``compute_drift_by_adr`` aggregates per-PR
findings across a batch of merged PRs, producing one entry per drifted
ADR with the union of contributing PRs.

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
    }
)


def _citation_drifts(adr: ADR, path: str, changed_symbols: frozenset[str]) -> bool:
    """Decide whether *path* drifts *adr* given the symbols changed in it.

    Symbol-aware (#9176):

    * **Bare-file citation** (empty cited-symbol set) → drifts on *any*
      touch of the file.  This preserves the legacy file-granular
      behaviour the P2 gate and the existing drift tests rely on — except
      for the cross-cutting :data:`_SHARED_INFRA_MODULES`, where a bare
      citation is treated as a dependency mention and does *not* drift
      (it must be cited at ``:Symbol`` granularity to drift).
    * **Symbol-qualified citation** (non-empty cited-symbol set) → drifts
      only when a symbol the diff reports as changed for this file
      matches one of the cited symbols.  A file-only diff (no symbol
      evidence) therefore does *not* drift a symbol-granular citation, so
      unrelated churn in a high-churn shared module no longer flags the
      ADR — the systemic false positive behind #9176.
    """
    cited_symbols = adr.source_symbols.get(path, frozenset())
    if not cited_symbols:
        return path not in _SHARED_INFRA_MODULES
    return bool(cited_symbols & changed_symbols)


def compute_drift(
    adr_index: ADRIndex,
    pr_number: int,
    changed_files: Iterable[str],
) -> list[DriftFinding]:
    """Return drift findings for one PR's file diff.

    Drift is symbol-aware (#9176): an ADR that cites a file at *symbol*
    granularity (``src/foo.py:Bar``) only drifts when the diff reports a
    change to that symbol; a bare ``src/foo.py`` citation still drifts on
    any change to the file.  ``changed_files`` entries may optionally carry
    a ``:Symbol`` tail to supply symbol evidence; bare paths — the
    production case — supply none.

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
        for adr in adrs:
            if not _citation_drifts(adr, path, changed_symbols):
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


def compute_drift_by_adr(
    adr_index: ADRIndex,
    pr_diffs: Iterable[tuple[int, Iterable[str]]],
) -> list[AdrRollupEntry]:
    """Group per-PR drift findings into one rollup entry per drifted ADR.

    ``pr_diffs`` is an iterable of ``(pr_number, changed_files)`` tuples
    — typically the PRs returned by one ``gh pr list`` page. Output is
    sorted by ADR number for deterministic processing.

    A PR whose diff includes the ADR's own file is silently skipped for
    that ADR — drift on that pair is considered resolved by the same PR
    (matches ``compute_drift``'s per-PR semantics).
    """
    pr_diffs = list(pr_diffs)
    if not pr_diffs:
        return []

    per_adr: dict[int, tuple[ADR, list[DriftFinding]]] = {}
    for pr_number, changed_files in pr_diffs:
        for finding in compute_drift(adr_index, pr_number, changed_files):
            slot = per_adr.setdefault(finding.adr.number, (finding.adr, []))
            slot[1].append(finding)

    return [
        AdrRollupEntry(adr=adr, contributors=tuple(findings))
        for _, (adr, findings) in sorted(per_adr.items())
    ]
