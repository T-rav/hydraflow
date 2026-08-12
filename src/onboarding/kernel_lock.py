"""Kernel lock — the stamped child's record of WHICH building code stamped it.

Slice 1 of #11060. A stamped repo previously recorded nothing about its own
provenance: no kernel version, no file hashes — so "am I current?" was
unanswerable from the child's artifacts (a succession bug by the
institutional-continuity rule, and the reason both live children were
stale-by-construction). This module is the pure half of the fix:

* :func:`build_lock` — fold a stamp *plan* into the lock document
  (building-code version + the stamping spec + per-file ownership and
  content hash of the PRESCRIBED content).
* :func:`compare` — classify each locked file against (a) the CURRENT
  prescription for the same spec and (b) the child's on-disk content:
  ``CURRENT`` / ``KERNEL_UPDATED`` (the building code moved on) /
  ``LOCALLY_MODIFIED`` (the child diverged) / ``MISSING``.

The lock lives at the child's repo root (``hydraflow-kernel.lock``) and is
COMMITTED — ``.hydraflow/`` is gitignored in children, and a record that
isn't in the repo is not a record. It is written when absent and refreshed
whenever its content would differ (changed prescription, diverged lock);
a byte-identical re-stamp writes nothing — it is the kernel's statement of
the prescription, not a mutation journal (git history is the journal).

No imports from ``kernel_writer`` — the writer imports *this* module; the
staleness CLI wires the two together. Keeps the dependency one-directional.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: The building-code version children are stamped against. Calendar-versioned;
#: bumped whenever the kernel's prescribed content changes semantically (the
#: BuildingCodeLoop — #11060 slice 4 — will own the bump + child update PRs).
BUILDING_CODE_VERSION = "2026.08.12"

KERNEL_LOCK_FILENAME = "hydraflow-kernel.lock"


class FileFreshness(StrEnum):
    """One locked file's state against the current code + the child's disk."""

    CURRENT = "current"
    KERNEL_UPDATED = "kernel_updated"  # building code moved on; child is stale
    LOCALLY_MODIFIED = "locally_modified"  # child diverged from what was stamped
    MISSING = "missing"  # locked file absent from the child


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def build_lock(
    *,
    spec_fields: dict[str, object],
    plan: Sequence[tuple[str, str, object]],
) -> dict[str, object]:
    """The lock document for one stamp run.

    ``plan`` rows are ``(relative_path, prescribed_content, ownership)`` — the
    kernel writer's plan, verbatim. The hash recorded is of the *prescribed*
    content (what the kernel says the file should be), which is what makes
    ``LOCALLY_MODIFIED`` distinguishable from ``KERNEL_UPDATED`` later.
    """
    return {
        "building_code_version": BUILDING_CODE_VERSION,
        "spec": spec_fields,
        "files": {
            rel: {"ownership": str(ownership), "sha256": _sha256(content)}
            for rel, content, ownership in plan
        },
    }


def dump_lock(lock: dict[str, object]) -> str:
    """Stable serialization (sorted keys, trailing newline) — diff-friendly."""
    return json.dumps(lock, indent=2, sort_keys=True) + "\n"


def load_lock(child_root: Path) -> dict[str, object] | None:
    """Read the child's lock; ``None`` when absent (pre-#11060 stamp)."""
    path = child_root / KERNEL_LOCK_FILENAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


@dataclass(frozen=True, slots=True)
class StalenessReport:
    """The child's freshness against the current building code."""

    locked_version: str
    current_version: str
    files: dict[str, FileFreshness]

    @property
    def version_stale(self) -> bool:
        return self.locked_version != self.current_version

    @property
    def stale_files(self) -> list[str]:
        """Files the building code has moved past (the update-PR worklist)."""
        return sorted(
            path
            for path, state in self.files.items()
            if state is FileFreshness.KERNEL_UPDATED
        )

    @property
    def modified_files(self) -> list[str]:
        """Files the child changed locally (never auto-overwritten; surfaced)."""
        return sorted(
            path
            for path, state in self.files.items()
            if state is FileFreshness.LOCALLY_MODIFIED
        )


def compare(
    lock: dict[str, object],
    *,
    current_plan: Sequence[tuple[str, str, object]],
    child_root: Path,
) -> StalenessReport:
    """Classify every locked file against the current prescription + the disk.

    Precedence per file: ``MISSING`` (not on disk) beats everything;
    ``KERNEL_UPDATED`` (current prescription differs from the locked hash)
    beats ``LOCALLY_MODIFIED`` (disk differs from the locked hash) — when the
    code moved on, the update path handles the merge and the local diff is
    part of that conversation, not a separate verdict.
    """
    locked_files_raw = lock.get("files")
    locked_files: dict[str, dict[str, object]] = (
        {
            str(path): dict(meta)
            for path, meta in locked_files_raw.items()
            if isinstance(meta, dict)
        }
        if isinstance(locked_files_raw, dict)
        else {}
    )
    current_hashes = {
        rel: _sha256(content) for rel, content, _ownership in current_plan
    }

    states: dict[str, FileFreshness] = {}
    for path, meta in locked_files.items():
        locked_hash = str(meta.get("sha256", ""))
        dest = child_root / path
        if not dest.is_file():
            states[path] = FileFreshness.MISSING
            continue
        current_hash = current_hashes.get(path)
        if current_hash is not None and current_hash != locked_hash:
            states[path] = FileFreshness.KERNEL_UPDATED
            continue
        disk_hash = _sha256(dest.read_text(encoding="utf-8", errors="replace"))
        if disk_hash != locked_hash:
            states[path] = FileFreshness.LOCALLY_MODIFIED
        else:
            states[path] = FileFreshness.CURRENT

    return StalenessReport(
        locked_version=str(lock.get("building_code_version", "unknown")),
        current_version=BUILDING_CODE_VERSION,
        files=states,
    )


def render_staleness(report: StalenessReport) -> str:
    """Human-readable staleness summary (the `make kernel-staleness` output)."""
    lines = [
        f"building code: locked={report.locked_version} "
        f"current={report.current_version} "
        f"({'STALE' if report.version_stale else 'current'})",
        f"files: {len(report.files)} locked · "
        f"{len(report.stale_files)} kernel-updated · "
        f"{len(report.modified_files)} locally-modified · "
        f"{sum(1 for s in report.files.values() if s is FileFreshness.MISSING)} missing",
    ]
    for path in report.stale_files:
        lines.append(f"  KERNEL_UPDATED   {path}")
    for path in report.modified_files:
        lines.append(f"  LOCALLY_MODIFIED {path}")
    for path, state in sorted(report.files.items()):
        if state is FileFreshness.MISSING:
            lines.append(f"  MISSING          {path}")
    return "\n".join(lines) + "\n"
