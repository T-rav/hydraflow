---
id: "01M15RKRY48S4039D4NPNPR962"
name: "Purpose"
kind: "policy"
bounded_context: "shared-kernel"
code_anchor: "src/onboarding/kernel_writer.py:KernelSpec"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-08-28T00:00:00+00:00"
updated_at: "2026-08-28T00:00:00+00:00"
---

## Definition

The first layer of the PAAA governance model (ADR-0143): what a repository is *for* — its direction, goals, set-points, and the intent the work serves. It answers "what is this thing trying to do?" for a system arriving at the repository cold, with no institutional memory. Purpose is the one PAAA layer **nothing checks**. It now has a declaration surface — #11748 landed the `purpose:` block in `charter.yaml`, parsed into `Purpose` (`src/charter.py`) — but **no drift check reads it**, and none should be added without a ruling saying what checking intent would even mean. Outside the charter it still lives implicitly in `README.md` prose, in the one-line description the onboarding kernel stamps into a new repository (`KernelSpec.description`), and in milestone and epic text; nothing reads any of those as a statement of intent either.

## Invariants

- Purpose is declarative intent, never an executable check — nothing today decides anything against it.
- Changing Purpose is an enactment reserved to the operator (ENACT, not RATIFY); the system cannot enlarge its own mandate.
- Purpose is not Articles: a goal the repository is aiming at is not a rule that must remain true.
