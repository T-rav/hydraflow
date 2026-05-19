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


def compute_drift(
    adr_index: ADRIndex,
    pr_number: int,
    changed_files: Iterable[str],
) -> list[DriftFinding]:
    """Return drift findings for one PR's file diff.

    Findings are sorted by ADR number for deterministic output.
    """
    files = list(changed_files)
    src_files = [f for f in files if f.startswith("src/")]
    if not src_files:
        return []
    by_path = adr_index.adrs_touching(src_files)

    adr_hits: dict[int, tuple[ADR, list[str]]] = {}
    for path, adrs in by_path.items():
        for adr in adrs:
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
