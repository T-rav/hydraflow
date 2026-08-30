"""Dispatch check specs to registered check functions and collect findings."""

from __future__ import annotations

from . import registry
from .models import CheckContext, CheckSpec, Finding, Status
from .na_justifications import NA_JUSTIFICATIONS


def run_checks(specs: list[CheckSpec], ctx: CheckContext) -> list[Finding]:
    findings: list[Finding] = []
    for spec in specs:
        findings.append(_run_one(spec, ctx))
    return findings


def _run_one(spec: CheckSpec, ctx: CheckContext) -> Finding:
    fn = registry.get(spec.check_id)
    if fn is None:
        return Finding(
            check_id=spec.check_id,
            status=Status.NOT_IMPLEMENTED,
            severity=spec.severity,
            principle=spec.principle,
            source=spec.source,
            what=spec.what,
            remediation=spec.remediation,
            message=(
                f"check {spec.check_id} has an ADR row but no implementation — "
                "the ADR and the audit have drifted"
            ),
        )
    try:
        result = fn(ctx)
    except Exception as exc:  # noqa: BLE001 — surface check crashes as findings
        return Finding(
            check_id=spec.check_id,
            status=Status.FAIL,
            severity=spec.severity,
            principle=spec.principle,
            source=spec.source,
            what=spec.what,
            remediation=spec.remediation,
            message=f"check raised {type(exc).__name__}: {exc}",
        )
    # Backfill metadata from the spec so check functions only set status + message.
    result.severity = result.severity or spec.severity
    result.principle = result.principle or spec.principle
    result.source = result.source or spec.source
    result.what = result.what or spec.what
    result.remediation = result.remediation or spec.remediation
    return _classify_na(result)


def _classify_na(result: Finding) -> Finding:
    """An unregistered ``NA`` is an ``INERT`` check, not a passing one.

    ``NA`` is a claim that a check looked at its subject and found it
    legitimately absent. That claim has to be registered in
    :data:`NA_JUSTIFICATIONS` with a reason. A check that reports ``NA``
    without one has not earned the benefit of the doubt: the far more common
    cause is that its subject VANISHED and nobody noticed, which is exactly how
    P2.3/P2.4/P2.6/P2.7 stayed green from the day they merged.

    Making the unregistered case loud is what keeps the table honest. If an
    unknown ``NA`` were quietly tolerated, the registry would be decoration.
    """
    if result.status is not Status.NA:
        return result
    if result.check_id in NA_JUSTIFICATIONS:
        return result
    result.status = Status.INERT
    result.message = (
        f"{result.message} — reported NA, but {result.check_id} has no entry in "
        "na_justifications.NA_JUSTIFICATIONS, so the audit cannot tell a subject "
        "that legitimately does not apply from one that has vanished. Treated as "
        "INERT: the audit is advertising a check it did not perform."
    ).lstrip(" —")
    return result


# Telemetry checks measure the CODEBASE, not the change under test —
# ADR-0044 words P10.3 as "reports ... as a warning", and its history scan
# runs in every open PR's CI, so its WARN blamed unrelated PRs and forced
# consent-gated baseline advances for compliant work (#9902). Their WARN is
# reported but never flips the exit code; per-PR enforcement is P10.6.
# P10.7 is likewise a history scan (issue-close false-close detector, #10354):
# it surfaces closes with no fix delta for re-triage but cannot blame the PR
# under test, so it must never fail PR CI.
TELEMETRY_CHECKS = frozenset({"P10.3", "P10.7"})

# ADVISORY checks are CULTURAL corpus scans that measure the ADR/doc corpus,
# not the change under test, and start life non-blocking on purpose. This set is
# empty today: P1.17 (ADR-0113 lineage) began here, WARNing while the seed pass
# (#10674 child 3) backfilled Precedent:/Divergence: lines across the
# control-plane ADRs, and was removed once every control-plane ADR carried a line
# (#10674 child 5). It is now STRUCTURAL — a control-plane ADR missing a lineage
# line, or a Divergence citing no receipt, FAILs the audit. The constant is kept
# (empty) as the seam the next advisory-then-escalated corpus check plugs into.
ADVISORY_CHECKS: frozenset[str] = frozenset()

# Checks whose WARN is reported but never fails the audit gate.
_NON_BLOCKING_WARN_CHECKS = TELEMETRY_CHECKS | ADVISORY_CHECKS


def overall_exit_code(findings: list[Finding]) -> int:
    """0 only when every finding is PASS or a JUSTIFIED NA; 1 otherwise.

    This used to read "0 if every finding is PASS/NA", and that is the single
    line that let four checks advertise themselves for months while measuring
    nothing (#8383/#8386). ``NA`` is still green — but only the registered,
    reasoned ``NA`` that survives :func:`_classify_na`. Everything else that
    declines to produce a verdict, ``INERT`` included, is a red audit.
    """
    bad = {Status.FAIL, Status.WARN, Status.INERT, Status.NOT_IMPLEMENTED}
    return (
        1
        if any(
            f.status in bad
            and not (
                f.check_id in _NON_BLOCKING_WARN_CHECKS and f.status is Status.WARN
            )
            for f in findings
        )
        else 0
    )
