"""Pure selection of burn-down units (per dimension+file) from the backlog."""

from __future__ import annotations

from dataclasses import dataclass

from disturbance.models import Finding


@dataclass(frozen=True)
class BurndownUnit:
    dimension: str
    path: str
    signatures: tuple[str, ...]
    fix_prompt: str
    dedup_key: str


def select_units(
    per_dim: list[tuple[str, str, list[Finding], dict[str, int]]],
    *,
    deduped: set[str],
    cap: int,
) -> list[BurndownUnit]:
    """Pick up to ``cap`` per-file burn-down units, smallest-file-first.

    ``per_dim`` entries are ``(dimension, fix_prompt, current_findings, baseline)``.
    Only findings whose signature is still in ``baseline`` are backlog. Units whose
    ``dedup_key`` is in ``deduped`` (an open PR already exists) are skipped.
    """
    units: list[BurndownUnit] = []
    for dimension, fix_prompt, findings, baseline in per_dim:
        by_file: dict[str, list[str]] = {}
        for f in findings:
            if f.signature in baseline:
                by_file.setdefault(f.path, []).append(f.signature)
        for path, sigs in by_file.items():
            dedup_key = f"disturbance:{dimension}:{path}"
            if dedup_key in deduped:
                continue
            units.append(
                BurndownUnit(
                    dimension=dimension,
                    path=path,
                    signatures=tuple(sorted(sigs)),
                    fix_prompt=fix_prompt,
                    dedup_key=dedup_key,
                )
            )
    # smallest first: fewest signatures per unit, then path for determinism
    units.sort(key=lambda u: (len(u.signatures), u.path))
    return units[:cap]
