"""Adopt flow — audit an EXISTING repo against the building code, never stamp blind.

Slice 3 of #11060. Greenfield stamping writes into an empty directory; a
brownfield project has files the operator owns, and blindly stamping over them
is exactly the blast the ownership model exists to prevent. This module is the
read-only audit that precedes any brownfield stamp: for every file the kernel
would prescribe, classify what stamping WOULD do —

* ``NEW``              — absent; a plain stamp writes it.
* ``IDENTICAL``        — present and byte-equal to the prescription; no-op.
* ``DIFFERS_TEMPLATE`` — present, differs, template-owned: a plain stamp
                         SKIPS it; ``FORCE=1`` would overwrite. The operator
                         decides which side is right.
* ``DIFFERS_PRODUCT``  — present, differs, product-owned: never overwritten,
                         not even under force. Informational.

Nothing is written. The CLI (``make adopt DIR=``) prints the classification and
the exact next-step commands; acting on them stays a deliberate operator step
(the same printed-not-automated discipline as the stamp's residual steps).
Proposing the diff *as a PR* is the plugin-plane follow-up (the guidance layer
of the three-plane ruling), not this slice.

Pure over the kernel's own prescription — one source of truth for "what would
the building code stamp today" (`kernel_writer.prescription`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from onboarding.kernel_writer import KernelSpec, Ownership, prescription


class AdoptAction(StrEnum):
    """What a stamp would do to one prescribed file in this repo."""

    NEW = "new"
    IDENTICAL = "identical"
    DIFFERS_TEMPLATE = "differs_template"
    DIFFERS_PRODUCT = "differs_product"


@dataclass(frozen=True, slots=True)
class AdoptReport:
    """The brownfield audit: per-file classification + the derived counts."""

    files: dict[str, AdoptAction]

    def count(self, action: AdoptAction) -> int:
        return sum(1 for state in self.files.values() if state is action)

    @property
    def safe_to_stamp(self) -> bool:
        """A plain stamp touches only NEW files — nothing existing changes."""
        return self.count(AdoptAction.DIFFERS_TEMPLATE) == 0


def adoption_report(
    spec: KernelSpec,
    target: Path,
    *,
    hydraflow_root: Path | None = None,
    plan: Sequence[tuple[str, str, Ownership]] | None = None,
) -> AdoptReport:
    """Classify every prescribed file against the existing tree. Writes nothing.

    ``plan`` is injectable for tests; by default the live prescription is used.
    """
    rows = plan if plan is not None else prescription(spec, hydraflow_root)
    root = Path(target).expanduser().resolve()
    files: dict[str, AdoptAction] = {}
    for rel, content, ownership in rows:
        dest = root / rel
        if not dest.is_file():
            files[rel] = AdoptAction.NEW
            continue
        existing = dest.read_text(encoding="utf-8", errors="replace")
        if existing == content:
            files[rel] = AdoptAction.IDENTICAL
        elif ownership is Ownership.PRODUCT:
            files[rel] = AdoptAction.DIFFERS_PRODUCT
        else:
            files[rel] = AdoptAction.DIFFERS_TEMPLATE
    return AdoptReport(files=files)


def render_adopt(report: AdoptReport, target: Path) -> str:
    """The operator-facing audit + the exact next steps (printed, not automated)."""
    lines = [f"adopt audit for {target} (#11060 slice 3 — read-only):"]
    lines.append(
        f"  {report.count(AdoptAction.NEW)} new · "
        f"{report.count(AdoptAction.IDENTICAL)} identical · "
        f"{report.count(AdoptAction.DIFFERS_TEMPLATE)} differ (template-owned) · "
        f"{report.count(AdoptAction.DIFFERS_PRODUCT)} differ (product-owned, "
        "never overwritten)"
    )
    for rel, state in sorted(report.files.items()):
        if state is AdoptAction.DIFFERS_TEMPLATE:
            lines.append(f"  DIFFERS(template) {rel}  ← FORCE=1 would overwrite")
    for rel, state in sorted(report.files.items()):
        if state is AdoptAction.DIFFERS_PRODUCT:
            lines.append(f"  DIFFERS(product)  {rel}  ← kept under any stamp")
    lines.append("next steps (deliberate operator actions):")
    if report.safe_to_stamp:
        lines.append(
            f"  make stamp DIR={target}   # plain stamp touches only NEW files"
        )
    else:
        lines.append(
            f"  review the DIFFERS(template) files above, then either keep the "
            f"local versions (make stamp DIR={target} — they are skipped) or "
            f"adopt the kernel's (make stamp DIR={target} FORCE=1)"
        )
    lines.append(
        f"  make kernel-staleness DIR={target}   # after stamping: freshness record"
    )
    return "\n".join(lines) + "\n"
