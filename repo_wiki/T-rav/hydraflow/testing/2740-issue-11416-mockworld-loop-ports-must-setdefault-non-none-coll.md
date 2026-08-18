---
id: 2740
topic: testing
source_issue: 11416
source_phase: plan
created_at: 2026-08-18T03:21:19.601679+00:00
status: active
corroborations: 1
---

# MockWorld._loop_ports must setdefault non-None collaborator kwargs

Rule: In `tests/scenarios/fakes/mock_world.py`, the `_loop_ports` block must `setdefault` collaborator kwargs (e.g., `wiki_compiler`) onto the `MockWorld(...)` constructor — only when non-None — so `world.run_with_loops(["repo_wiki"])` reaches the compiler.

- Without this, seeded ports from the catalog builder never reach the loop constructor.

**Why:** A broken link in the seeding chain (catalog → MockWorld ports → loop ctor) makes the entire port-seeding effort dead.
