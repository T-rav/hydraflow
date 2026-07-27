---
id: 0238
topic: architecture
source_issue: 10658
source_phase: plan
created_at: 2026-07-26T15:42:45.056011+00:00
status: active
corroborations: 1
---

# Restore loop runs under exec; keep merge inline

The pin AST-extracts `src/server.py`'s boot restore loop (~L228-265) and `exec`s it with a fixed namespace. Do not reference new module-level helpers from inside the loop body — they will `NameError`.

Precedent at `src/server.py:295` imports inside the body. If a helper is needed, import it within the loop.

**Why:** The exec namespace is fixed and cannot resolve names added to module scope after the pin was authored.
