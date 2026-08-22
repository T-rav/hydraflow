---
id: 2777
topic: testing
source_issue: 11541
source_phase: plan
created_at: 2026-08-22T00:00:10.177857+00:00
status: active
corroborations: 1
---

# Atomic revalidation-then-spawn for brokered child dispatch

Revalidate stop/drain, lease epoch, phase attempt, live label, and policy revision in one atomic step immediately before spawning a child process — never split the check from the claim.

- `src/director_broker.py` must perform revalidation and ownership claim as a single operation.
- An interleaving test (not a code comment) must prove that a label change, epoch bump, or policy-revision change between command and spawn yields zero dispatches.

**Why:** A gap between revalidation and spawn produces exactly the duplicate or late dispatch that the safety boundary forbids; under-dispatch is recoverable, over-dispatch is not.
