"""Pure blast-radius stratification for sampled re-audit (#10370).

Acceptance sampling elevates the sampling probability for high-blast-radius
changes (decided): structural / ADR-touching, security-adjacent paths,
migrations, and changes touching the gauntlet or merge policy itself. This
module is the pure classifier + the per-class stratum weight; ``sampling``
multiplies the governed base rate by the weight (capped at 1.0).

Precedence when a change matches several classes (decided v1): gauntlet >
migration > security > structural > routine — the most operationally dangerous
class wins so a merge that both touches the gauntlet and a migration samples at
the gauntlet weight, never a diluted average.
"""

from __future__ import annotations

from audit.models import BlastRadiusClass, MergedChange

# v1 stratum weights (multipliers on the governed base rate; planning-picked).
# routine = 1x; elevated classes sample more aggressively. Capped at 1.0 in the
# sampler so a weighted probability never exceeds certainty.
_STRATUM_WEIGHTS: dict[str, float] = {
    "routine": 1.0,
    "structural": 2.0,
    "security": 3.0,
    "migration": 3.0,
    "gauntlet": 4.0,
}

# Path substrings that mark each elevated class. Matched case-insensitively
# against every changed path (repo-root-relative, posix). Deliberately broad —
# over-sampling a high-blast-radius class is the safe direction.
_GAUNTLET_MARKERS: tuple[str, ...] = (
    "merge_policy",
    "gauntlet",
    "branch_protection",
    "compliance",
    "src/audit/",
    "escape",
    "quality_gate",
    ".github/workflows/",
)
_SECURITY_MARKERS: tuple[str, ...] = (
    "security",
    "auth",
    "secret",
    "credential",
    "token",
    "trust",
)
_MIGRATION_MARKERS: tuple[str, ...] = (
    "migration",
    "migrations/",
    "schema",
    "alembic",
)
_STRUCTURAL_MARKERS: tuple[str, ...] = (
    "docs/adr/",
    "adr-",
    "src/ports.py",
    "service_registry",
    "orchestrator.py",
    "orchestrator_",  # the orchestrator mixin family (#11547)
    "base_background_loop",
)


def _matches(paths: tuple[str, ...], markers: tuple[str, ...]) -> bool:
    lowered = [p.lower() for p in paths]
    return any(marker in path for path in lowered for marker in markers)


def _touches_adr_subject(change: MergedChange) -> bool:
    """A structural signal from the subject/body — an ADR reference without a
    file touch (e.g. ``feat(...): ... (ADR-0042)``) still elevates."""
    text = f"{change.subject}\n{change.body}".lower()
    return "adr-" in text or "adr " in text


def classify_blast_radius(change: MergedChange) -> BlastRadiusClass:
    """Return the single strongest blast-radius class for *change*. Pure."""
    paths = change.changed_paths
    if _matches(paths, _GAUNTLET_MARKERS):
        return "gauntlet"
    if _matches(paths, _MIGRATION_MARKERS):
        return "migration"
    if _matches(paths, _SECURITY_MARKERS):
        return "security"
    if _matches(paths, _STRUCTURAL_MARKERS) or _touches_adr_subject(change):
        return "structural"
    return "routine"


def stratum_weight(blast_class: str) -> float:
    """Sampling-rate multiplier for a blast-radius class (routine = 1.0)."""
    return _STRATUM_WEIGHTS.get(blast_class, 1.0)
