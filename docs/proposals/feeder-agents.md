# Feeder agents: generated intake from inside the repo

**Status:** proposal (2026-07-26). **Depends on:** the intake conventions (sentry/log ingest, report_issue), ADR-0103 (steering: the how/what boundary), the triage gate.

**Precedent:** scheduled static analysis / code-scanning tradition (linters, security scanners filing findings). **Divergence:** the scanner proposes intent-level *work*, not diagnostics — it touches set-point discovery, which the control model reserves for humans; hence the hard rule below.

## The gap

Intake today is reactive: production errors arrive through the ingest loops, dependencies through their bumps, staleness through the sweeper, everything else through the operator's asks. Nothing surveys the repository itself for latent work: drift between record and code, dead ends, debt the detectors know about but nobody has asked to burn down, test-thin surfaces, unshipped intent sitting in decision records. The factory only works on what something else already noticed.

## Design

Run one or more **feeder agents** inside a registered repository whose only job is generating intake: survey the repo against a defined signal set and file *issue proposals* the pipeline then triages like any other work.

Hard rule (the set-point guardrail): **scouts propose, triage disposes.** A feeder's write surface is issue creation only — never merges, never label transitions past the front door, never edits. Proposals wear a distinct label so the triage gate (and the human, at whatever sampling rate trust has earned) decides what becomes work. The feeder widens the funnel; it never holds the valve.

Signals (initial set, each with a provenance line on the filed proposal):
1. Record/code drift the conformance and drift detectors already compute but only report
2. Detector-known debt above a staleness threshold (dampener backlog items nobody scheduled)
3. Test-thin surfaces: files/modules materially below the repo's coverage floor neighborhood
4. Dead ends: feature flags, TODO clusters, and orphaned modules with no inbound references
5. Unshipped intent: accepted decision records whose deliverables never landed

Bounds: kill switch and watchdog like every loop; a finding-rate budget (a generator without a budget is an intake flood); dedupe against open issues before filing; read-only plus issue-create permissions, nothing else.

## Acceptance

- Proposal acceptance rate at triage is the feeder's trust metric, tracked like intervention rates: a feeder whose proposals are mostly declined gets its budget cut, not its volume raised.
- Intake share by source becomes visible (reactive vs generated), so the meter can say whether generated discovery pays.
- No feeder proposal ever reaches implementation without passing the same triage gate as human-filed work.
