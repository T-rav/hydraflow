---
id: 1416
topic: gotchas
source_issue: 11292
source_phase: plan
created_at: 2026-08-16T01:48:07.890744+00:00
status: active
corroborations: 1
---

# Port signature changes require synchronized three-mirror commit

When modifying a Protocol method on `src/ports.py`, land the Port + `PRManager` + `FakeGitHub` implementations in one commit/task — never split across tasks. 

Example: adding `find_class_issue` required edits to `src/ports.py`, `src/pr_manager.py`, and `src/mockworld/fakes/fake_github.py` all gated under task P2 with no sub-split.

**Why:** Protocol-signature drift between mirrors causes FakeGitHub-based tests to pass while real `PRManager` fails at runtime (or vice versa), masking defects until integration.
