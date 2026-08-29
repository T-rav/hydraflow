"""``PythonDecisionEngine`` — the reference ``DecisionEngine`` (#11749).

Facts in, decisions out. This module is the parity target for #11750's OPA
pilot: whatever Rego decides, it must decide what this decides, over the same
recorded facts.

**What this module may not do.** Per epic #11752 the decision engine never runs
pytest, inspects git, launches agents, touches worktrees, repairs code,
schedules, routes models, manages PRs, or owns lifecycle state. It reads no
file and opens no socket — every input arrives as a ``Fact``. The two
``adr_conformance`` imports below are an enum and a pure classifier; the
repo-reading half of that module is deliberately not imported, and
``tests/architecture/test_policy_engine_is_pure.py`` holds this module's import
set to an allow-list so the seam cannot rot into a layer.

**Fail-closed on thin evidence.** A subject missing any fact its standard needs
raises :class:`MissingFactError` rather than defaulting. Defaults are how a
gate stops firing quietly: absent ``resolved``, an unpaid grandfathered debt
would default to *still grandfathered* and a violation would silently become a
pass. An unknown standard raises :class:`UnsupportedStandardError` for the same
reason — an engine that cannot judge an article must say so, not return
nothing and let the caller read no decisions as no problems.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from adr_conformance import CheckOutcome, EnforcementClass
from adr_conformance_remediation import RemediationAction, classify_remediation_over
from policy.facts import STANDARD_ADR_CONFORMANCE, STANDARD_ADR_ENFORCEMENT
from policy.models import Charter, DecisionStatus, StandardDecision

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

    from policy.models import Fact, FactValue


class DecisionEngineError(Exception):
    """Base class for a decision that could not be made."""


class MissingFactError(DecisionEngineError):
    """A subject's evidence is missing a fact its standard requires."""


class UnsupportedStandardError(DecisionEngineError):
    """This engine has no ruleset for a standard present in the facts."""


#: The enforcement classes that constitute unenforced-decision debt. ``REAL``
#: is the only compliant class; the tautology heuristic
#: (``adr_conformance.check_is_tautological``) is advisory and deliberately not
#: folded in, matching ``classify_adr_enforcement``.
_DEBT_CLASSES: frozenset[str] = frozenset(
    {EnforcementClass.WEAK.value, EnforcementClass.MISSING.value}
)

#: Facts every ``adr_enforcement`` subject must carry. All five are
#: load-bearing: dropping ``resolved`` alone turns a paid debt back into a
#: grandfathered one, and dropping ``binds`` disarms the regulated-charter rule
#: below without reddening anything — so both are required, never defaulted.
_ENFORCEMENT_REQUIRED: tuple[str, ...] = (
    "enforcement_class",
    "in_baseline_snapshot",
    "resolved",
    "exempt",
    "binds",
)

#: ADR-0123 ``**Binds:**`` values that constrain the FACTORY itself. ``both``
#: is included because ADR-0123 defines it as binding work *and* factory.
_BINDS_FACTORY: frozenset[str] = frozenset({"factory", "both"})

#: Facts every ``adr_conformance`` subject must carry. ``rename_match`` is
#: optional by design — its absence *is* the observation "no rename detected".
_CONFORMANCE_REQUIRED: tuple[str, ...] = ("outcome", "attempts", "max_attempts")


def _indexed(facts: Sequence[Fact], required: tuple[str, ...]) -> dict[str, FactValue]:
    by_key = {fact.key: fact.value for fact in facts}
    missing = [key for key in required if key not in by_key]
    if missing:
        subject = facts[0].subject if facts else "<no facts>"
        raise MissingFactError(
            f"{subject}: missing required fact(s) {missing}. The engine reads no "
            "files, so a fact it was not given is a collector bug — fix the "
            "collector rather than defaulting the value here."
        )
    return by_key


class PythonDecisionEngine:
    """Pure-Python reference implementation of :class:`policy.models.DecisionEngine`."""

    def decide(
        self, facts: Sequence[Fact], charter: Charter | None = None
    ) -> list[StandardDecision]:
        """Judge every ``(standard, subject)`` the charter places in force.

        Output is sorted by ``(standard, subject)`` so two runs over the same
        ledger produce byte-identical decisions regardless of fact ordering —
        a replay from ``facts.jsonl`` must not depend on write order.
        """
        active = charter if charter is not None else Charter()
        grouped: dict[tuple[str, str], list[Fact]] = {}
        for fact in facts:
            if not active.governs(fact.standard):
                continue
            grouped.setdefault((fact.standard, fact.subject), []).append(fact)

        decisions: list[StandardDecision] = []
        for standard, subject in sorted(grouped):
            subject_facts = grouped[(standard, subject)]
            if standard == STANDARD_ADR_ENFORCEMENT:
                decisions.append(
                    self._decide_enforcement(subject, subject_facts, active)
                )
            elif standard == STANDARD_ADR_CONFORMANCE:
                decisions.append(self._decide_conformance(subject, subject_facts))
            else:
                raise UnsupportedStandardError(
                    f"no ruleset for standard {standard!r} (subject {subject!r}). "
                    "An engine that cannot judge an article must refuse, not "
                    "return silence that reads as compliance."
                )
        return decisions

    @staticmethod
    def _decide_enforcement(
        subject: str, facts: Sequence[Fact], charter: Charter
    ) -> StandardDecision:
        """The ADR-enforcement ratchet's rule, re-derived from primitive facts.

        The ladder below is deliberately NOT a call into
        ``adr_conformance.live_grandfathered``. That function answers with set
        arithmetic over the whole ADR population
        (``baseline_snapshot - resolved - exempted``); this answers per subject
        by ordered predicates. Two different computations over the same
        evidence — which is the only arrangement under which
        ``test_policy_adr_enforcement_parity`` can fail, and therefore the only
        one under which it means anything.
        """
        by_key = _indexed(facts, _ENFORCEMENT_REQUIRED)
        cls = str(by_key["enforcement_class"])
        exempt = bool(by_key["exempt"])
        in_snapshot = bool(by_key["in_baseline_snapshot"])
        resolved = bool(by_key["resolved"])
        binds = str(by_key["binds"])

        if cls not in _DEBT_CLASSES:
            return StandardDecision(
                standard=STANDARD_ADR_ENFORCEMENT,
                subject=subject,
                status=DecisionStatus.COMPLIANT,
                blocking=False,
                reason=f"enforcement classifies {cls} — bound to a real asserting check",
                remediation=RemediationAction.NONE,
                facts=list(facts),
            )
        if exempt:
            return StandardDecision(
                standard=STANDARD_ADR_ENFORCEMENT,
                subject=subject,
                status=DecisionStatus.EXEMPT,
                blocking=False,
                reason=(
                    f"{cls} but allow-listed as process-only in "
                    "docs/standards/adr_enforcement/exemptions.md"
                ),
                remediation=RemediationAction.NONE,
                facts=list(facts),
            )
        if (
            charter.is_regulated()
            and binds in _BINDS_FACTORY
            and cls == EnforcementClass.WEAK.value
        ):
            return StandardDecision(
                standard=STANDARD_ADR_ENFORCEMENT,
                subject=subject,
                status=DecisionStatus.VIOLATED,
                blocking=True,
                reason=(
                    f"WEAK enforcement on a Binds:{binds} decision under a "
                    "regulated charter — the ratchet does not carry "
                    "factory-binding debt in a regulated repo"
                ),
                remediation=RemediationAction.FILE_ISSUE,
                facts=list(facts),
            )
        if in_snapshot and not resolved:
            return StandardDecision(
                standard=STANDARD_ADR_ENFORCEMENT,
                subject=subject,
                status=DecisionStatus.GRANDFATHERED,
                blocking=False,
                reason=(
                    f"{cls} but carried by the frozen enforcement-debt baseline; "
                    "shrink-only — pay it down by giving the ADR a real check"
                ),
                remediation=RemediationAction.NONE,
                facts=list(facts),
            )
        return StandardDecision(
            standard=STANDARD_ADR_ENFORCEMENT,
            subject=subject,
            status=DecisionStatus.VIOLATED,
            blocking=True,
            reason=(f"{cls} enforcement debt that is neither grandfathered nor exempt"),
            remediation=RemediationAction.FILE_ISSUE,
            facts=list(facts),
        )

    @staticmethod
    def _decide_conformance(subject: str, facts: Sequence[Fact]) -> StandardDecision:
        """ADR-0100's runtime remediation, reached from facts.

        Unlike the enforcement lane this one *wraps* rather than re-derives:
        it calls the same ``classify_remediation_over`` the loop's old
        ``classify_remediation`` call now goes through, so migrating
        ``AdrConformanceLoop`` onto ``StandardDecision`` changed which object the
        loop reads, not which action it takes.
        """
        by_key = _indexed(facts, _CONFORMANCE_REQUIRED)
        rename = by_key.get("rename_match")
        decision = classify_remediation_over(
            adr_id=subject,
            outcome=CheckOutcome(str(by_key["outcome"])),
            rename_match=None if rename is None else str(rename),
            attempts=int(by_key["attempts"]),
            max_attempts=int(by_key["max_attempts"]),
        )
        acted = decision.action is not RemediationAction.NONE
        return StandardDecision(
            standard=STANDARD_ADR_CONFORMANCE,
            subject=subject,
            status=DecisionStatus.VIOLATED if acted else DecisionStatus.COMPLIANT,
            blocking=acted,
            reason=decision.reason,
            remediation=decision.action,
            facts=list(facts),
        )
