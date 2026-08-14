---
id: 1722
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T11:12:31.865671+00:00
status: active
corroborations: 1
supersedes: 1628
---

# Cassette baselines pin projection bytes; never add keys (ADR-0047)

Hand-authored cassettes (`list_workflow_runs.yaml`, `list_runs_for_workflow.yaml`) pin exact bytes of `FakeGitHub` projections — never add fields or reverse-derive display names.

Example: Neither projection gains a key when a new slot is introduced; a file-name-only seed projects its verbatim string with no reverse derivation to a display name.

**Why:** Cassettes are the trust boundary for fake-vs-live parity; mutating projection shape invalidates baselines that encode real GitHub API responses.
