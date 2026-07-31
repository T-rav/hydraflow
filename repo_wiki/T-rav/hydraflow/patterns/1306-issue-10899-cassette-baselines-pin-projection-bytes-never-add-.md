---
id: 1306
topic: patterns
source_issue: 10899
source_phase: plan
created_at: 2026-07-31T11:25:57.702216+00:00
status: active
corroborations: 1
---

# Cassette baselines pin projection bytes — never add keys or reverse-derive (ADR-0047)

Hand-authored cassettes (`list_workflow_runs.yaml`, `list_runs_for_workflow.yaml`) pin exact bytes of `FakeGitHub` projections. Adding a new field to a returned row, or reverse-deriving a display name from a file-name seed, breaks cassette replay.

- Neither projection gains a key when a new slot is introduced.
- A file-name-only seed projects its verbatim string from the repo-wide read — no reverse derivation to a display name exists.

**Why:** Cassettes are the trust boundary for fake-vs-live parity; mutating projection shape invalidates baselines that encode real GitHub API responses.
