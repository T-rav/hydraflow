"""Which claims are vitals (externalisable) and which are conformance (not).

The rule is in ``docs/standards/vitals_conformance/README.md``:

    If the claim is *what the number is*, it is vitals and may live in an
    external data plane. If the claim is *that a rule holds*, it is conformance
    and must be answerable offline from a clean checkout.

Registration is manual and explicit, for the same reason
``path_membership_registry`` is: discovery-by-convention would be the failure
mode one level up — a rule that quietly stops seeing its subject. A check
nobody registers is a check nobody classified.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

__all__ = [
    "CONFORMANCE_ROOTS",
    "Claim",
    "ClaimKind",
    "registered_claims",
    "repo_root",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class ClaimKind(StrEnum):
    VITALS = "vitals"
    """A measurement. May be emitted to an external plane."""

    CONFORMANCE = "conformance"
    """An assertion that a rule holds. Must be answerable offline."""


@dataclass(frozen=True, slots=True)
class Claim:
    """One registered artifact or gate, and what kind of claim it makes."""

    name: str
    kind: ClaimKind
    path: str
    """Repo-relative. Must resolve — a claim about a file that is gone is not a
    claim, and that is the #11673 lesson applied here."""

    why: str
    """The answer to "what breaks if the external plane is down?"."""


#: Directories whose contents are conformance by construction. Anything under
#: them enforces a rule rather than reporting a number, so the offline
#: constraint applies to the whole tree rather than per-file.
CONFORMANCE_ROOTS: tuple[str, ...] = (
    "tests/architecture",
    "tests/regressions",
)


def registered_claims() -> tuple[Claim, ...]:
    """Every classified artifact and gate."""
    return (
        # --- VITALS: counters. What the number is. ---------------------------
        Claim(
            name="erosion.mass",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/mass.yaml",
            why=(
                "god-class/file sizes. Losing the plane loses the trend, not the "
                "ratchet: test_mass_ratchet reads this file, not a service."
            ),
        ),
        Claim(
            name="erosion.suite_hygiene",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/suite_hygiene.yaml",
            why="parametrize copies and cross-file duplicates. A count.",
        ),
        Claim(
            name="erosion.suppressions",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/suppressions.yaml",
            why="how many suppressions exist. The shrink-only rule is the gate.",
        ),
        Claim(
            name="erosion.concentration",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/concentration.yaml",
            why="module fan-in counts.",
        ),
        Claim(
            name="erosion.traceability",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/traceability.yaml",
            why="untraced percentage. A fraction.",
        ),
        Claim(
            name="erosion.mock_spec",
            kind=ClaimKind.VITALS,
            path="disturbance/baselines/mock_spec.yaml",
            why="mock-spec violation count.",
        ),
        Claim(
            name="vitals.emitter",
            kind=ClaimKind.VITALS,
            path="scripts/emit_vitals.py",
            why=(
                "the thing that ships the counters. Carries no assertion that a "
                "gate holds, and a test in tests/test_emit_vitals.py enforces that."
            ),
        ),
        # --- CONFORMANCE: rules. That a rule holds. --------------------------
        Claim(
            name="ratchet.disturbance",
            kind=ClaimKind.CONFORMANCE,
            path="tests/test_disturbance_ratchet.py",
            why=(
                "shrink-only is a RULE over the counters above. The counts are "
                "vitals; 'it did not grow' is conformance and must hold offline."
            ),
        ),
        Claim(
            name="ratchet.mass",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_mass_ratchet.py",
            why="'no new god class beyond the baseline' is a rule, not a number.",
        ),
        Claim(
            name="ratchet.baseline_keys_resolve",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_ratchet_baseline_keys_resolve.py",
            why=(
                "'every baseline key still names a real file' — the guard that "
                "makes a re-keyed entry loud instead of reading as progress "
                "(#11680). Pure filesystem."
            ),
        ),
        Claim(
            name="path_membership.registry",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/path_membership_registry.py",
            why=(
                "'every path-membership entry resolves, and membership follows a "
                "module into a package' (#11673). Repo knowledge; unsamplable."
            ),
        ),
        Claim(
            name="adr.source_citations",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_adr_source_citations_exist.py",
            why="'every ADR citation resolves against the source tree'.",
        ),
        Claim(
            name="adr.enforcement_ratchet",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_adr_enforcement_ratchet.py",
            why="'accepted ADRs carry enforcement' is a rule about the ADRs.",
        ),
        Claim(
            name="credit_reraise.completeness",
            kind=ClaimKind.CONFORMANCE,
            path="tests/test_loop_credit_reraise_completeness.py",
            why=(
                "'no broad handler swallows a credit or likely-bug exception' — "
                "#6855's guard, which was absent for months while green (#11670)."
            ),
        ),
        Claim(
            name="mkdocs.strict",
            kind=ClaimKind.CONFORMANCE,
            path="tests/architecture/test_mkdocs_strict.py",
            why="'every cross-link resolves'. Builds the site locally.",
        ),
    )
