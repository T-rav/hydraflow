---
id: 1077
topic: testing
source_issue: 10567
source_phase: plan
created_at: 2026-07-25T23:37:32.613879+00:00
status: stale
corroborations: 1
stale_reason: source issue #10567 closed
---

# tests/test_ports.py has two parity lists that both need every method

`_REQUIRED_METHODS` gates existence (PRManager exposes the method); `_SIGNED_METHODS` gates signature match between `PRPort` and `PRManager`. Adding a method to only `_REQUIRED_METHODS` means param-name drift between the Protocol and the implementation ships silently.
**Why:** the two lists check different things — existence vs. signature parity — so updating one without the other leaves a real gap uncovered.
