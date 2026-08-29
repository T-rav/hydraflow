"""Fact collectors — the only half of the seam allowed to read the world.

Every repo read that a decision depends on happens here: scanning the ADR
corpus, loading the frozen enforcement baseline, parsing the exemption
allow-list, flattening a loop's in-flight ``AdrConformance``. The engine gets
the resulting ``Fact`` records and nothing else, which is what makes a decision
reproducible from ``facts.jsonl`` offline.

Collectors emit **primitive** observations, never derived verdicts. The ADR
enforcement collector emits ``in_baseline_snapshot`` / ``resolved`` / ``exempt``
rather than a single ``grandfathered`` boolean, precisely so the engine has to
re-derive ``baseline_snapshot - resolved - exempted`` for itself. A collector
that handed the engine the answer would make the parity test in
``tests/architecture/test_policy_adr_enforcement_parity.py`` tautological —
both sides would be reading the same helper's output rather than reaching the
same conclusion by different routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from adr_conformance import (
    enforcement_classification,
    load_enforcement_baseline,
    parse_exemptions,
)
from policy.models import Fact

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import datetime
    from pathlib import Path

    from adr_conformance import AdrConformance

#: Static enforcement debt: does each Accepted ADR's decision bind to a real,
#: runnable, asserting check? Gated by
#: ``tests/architecture/test_adr_enforcement_ratchet.py``.
STANDARD_ADR_ENFORCEMENT = "adr_enforcement"

#: Runtime conformance: do the checks an ADR cites still pass? Actuated by
#: ``AdrConformanceLoop`` (ADR-0100).
STANDARD_ADR_CONFORMANCE = "adr_conformance"

#: Every standard this module can collect for — the default charter.
COLLECTED_STANDARDS: tuple[str, ...] = (
    STANDARD_ADR_ENFORCEMENT,
    STANDARD_ADR_CONFORMANCE,
)

_ENFORCEMENT_SOURCE = "policy.facts.collect_adr_enforcement_facts"
_CONFORMANCE_SOURCE = "policy.facts.conformance_facts"


def adr_subject(number: int) -> str:
    """The canonical subject id for an ADR number: ``ADR-0091``."""
    return f"ADR-{number:04d}"


def collect_adr_enforcement_facts(
    repo_root: Path, *, observed_at: datetime
) -> list[Fact]:
    """Observe the enforcement-debt evidence for every Accepted ADR.

    Four facts per ADR, all primitive:

    * ``enforcement_class`` — ``REAL`` / ``WEAK`` / ``MISSING``
      (``adr_conformance.classify_adr_enforcement``).
    * ``in_baseline_snapshot`` — is the ADR in the frozen landing snapshot?
    * ``resolved`` — has its debt been claimed paid in the baseline JSON?
    * ``exempt`` — is it allow-listed as process-only?

    The engine derives ``grandfathered`` from the middle two; see the module
    docstring for why that derivation is not done here.
    """
    classes = enforcement_classification(repo_root)
    snapshot, resolved = load_enforcement_baseline(repo_root)
    exempted = frozenset(parse_exemptions(repo_root))

    facts: list[Fact] = []
    for number in sorted(classes):
        subject = adr_subject(number)
        observations: list[tuple[str, bool | str]] = [
            ("enforcement_class", classes[number].value),
            ("in_baseline_snapshot", number in snapshot),
            ("resolved", number in resolved),
            ("exempt", number in exempted),
        ]
        facts.extend(
            Fact(
                standard=STANDARD_ADR_ENFORCEMENT,
                subject=subject,
                key=key,
                value=value,
                observed_at=observed_at,
                source=_ENFORCEMENT_SOURCE,
            )
            for key, value in observations
        )
    return facts


def conformance_facts(
    conf: AdrConformance,
    *,
    rename_match: str | None,
    attempts: int,
    max_attempts: int,
    observed_at: datetime,
) -> list[Fact]:
    """Flatten one in-flight ``AdrConformance`` into the facts a decision needs.

    ``rename_match`` and ``attempts`` are the loop's own observations (a
    detected pytest-node rename, the per-ADR attempt counter), not properties
    of the ADR — they are collected here for the same reason the on-disk reads
    are: so the engine sees only facts.

    ``rename_match`` is omitted rather than emitted as an empty string when
    absent. "No rename was detected" and "a rename to the empty string was
    detected" must not serialize identically.
    """
    observations: list[tuple[str, bool | int | str]] = [
        ("outcome", conf.outcome.value),
        ("kind", conf.kind.value),
        ("attempts", attempts),
        ("max_attempts", max_attempts),
    ]
    if rename_match is not None:
        observations.append(("rename_match", rename_match))
    return [
        Fact(
            standard=STANDARD_ADR_CONFORMANCE,
            subject=conf.adr_id,
            key=key,
            value=value,
            observed_at=observed_at,
            source=_CONFORMANCE_SOURCE,
        )
        for key, value in observations
    ]
