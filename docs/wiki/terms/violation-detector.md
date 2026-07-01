---
id: "01KWFR9AWM3NX19D0C1W10NNMM"
name: "ViolationDetector"
kind: "port"
bounded_context: "shared-kernel"
code_anchor: "src/disturbance/detectors/base.py:ViolationDetector"
aliases: []
related: []
evidence: []
superseded_by: null
superseded_reason: null
confidence: "accepted"
created_at: "2026-07-01T21:10:16.212892+00:00"
updated_at: "2026-07-01T21:10:16.212894+00:00"
---

## Definition

The Sensor role (ADR-0094) in the Disturbance Dampener (ADR-0095): a pluggable protocol with a single pure method, detect(repo_root) -> list[Finding], that reads files only and produces no side effects. Each dimension in the registry (mock_spec, suppressions) binds one concrete ViolationDetector implementation. Findings carry a stable per-occurrence signature so the ratchet gate and the burn-down loop can count and diff violations per signature rather than as an undifferentiated total.

## Invariants

- detect() must be pure: it reads repository files and returns Findings, and must not mutate the repository or any baseline.
- Every Finding's signature must be stable across repeated detect() calls against unchanged source, since the ratchet gate diffs signatures against a persisted baseline.
