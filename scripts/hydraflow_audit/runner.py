"""Dispatch check specs to registered check functions and collect findings."""

from __future__ import annotations

from . import registry
from .models import CheckContext, CheckSpec, Finding, Status


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
# not the change under test, and start life non-blocking on purpose. P1.17
# (ADR-0113 lineage) WARNs while the seed pass (#10674 child 3) backfills
# Precedent:/Divergence: lines across the control-plane ADRs; like the
# telemetry checks its WARN is reported but never flips the exit code. It is
# slated to escalate to STRUCTURAL/blocking once every control-plane ADR carries
# a line (#10674 child 5), at which point it is removed from this set.
ADVISORY_CHECKS = frozenset({"P1.17"})

# Checks whose WARN is reported but never fails the audit gate.
_NON_BLOCKING_WARN_CHECKS = TELEMETRY_CHECKS | ADVISORY_CHECKS


def overall_exit_code(findings: list[Finding]) -> int:
    """0 if every finding is PASS/NA (or a non-blocking-WARN check); 1 otherwise."""
    bad = {Status.FAIL, Status.WARN, Status.NOT_IMPLEMENTED}
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
