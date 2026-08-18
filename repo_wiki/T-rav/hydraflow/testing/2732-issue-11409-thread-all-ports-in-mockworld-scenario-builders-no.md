---
id: 2732
topic: testing
source_issue: 11409
source_phase: plan
created_at: 2026-08-18T03:04:36.397135+00:00
status: active
corroborations: 1
---

# Thread all ports in MockWorld scenario builders, not just some

Rule: When constructing loops via `_build_repo_wiki` in `tests/scenarios/catalog/loop_registrations.py`, pass every port the loop accepts — including `wiki_compiler`. Pass `wiki_compiler=ports.get("wiki_compiler")` explicitly.

**Why:** An unwired port leaves `self._wiki_compiler is None`, and MockWorld silently no-ops before reaching Phase 8 (compile) — the scenario appears to pass while never exercising the intended code path.
