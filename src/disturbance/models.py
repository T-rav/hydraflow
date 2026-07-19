"""Core value objects for the disturbance dampener (ADR-0095)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    """One detected violation occurrence for a dimension.

    ``signature`` is ``f"{path}::{code}"`` — deliberately line-number-free so the
    baseline ratchet is drift-immune. Multiple occurrences may share a signature;
    the ratchet counts them.
    """

    dimension: str
    path: str
    signature: str
    message: str


@dataclass
class RatchetResult:
    """Outcome of comparing current detections to a ``{signature: count}`` baseline."""

    new: dict[str, int] = field(
        default_factory=dict
    )  # signature -> excess (current - baseline)
    resolved: dict[str, int] = field(
        default_factory=dict
    )  # signature -> shortfall (baseline - current)
    unchanged: tuple[str, ...] = ()
