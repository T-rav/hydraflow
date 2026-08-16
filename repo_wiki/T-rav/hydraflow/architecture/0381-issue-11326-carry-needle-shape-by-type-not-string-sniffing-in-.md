---
id: 0381
topic: architecture
source_issue: 11326
source_phase: plan
created_at: 2026-08-16T09:29:42.917635+00:00
status: active
corroborations: 1
---

# Carry needle shape by type, not string sniffing in class_key

Use separate typed dataclasses (`ConcreteNeedle` vs `PatternNeedle`) rather than inspecting the string payload to classify needles in `src/class_key.py`.

Example: `PatternNeedle` uses `Literal["regex", "ast"]`, while `ConcreteNeedle` carries `site`.

**Why:** Concrete paths like `src/foo.py` are valid regex, so string heuristics misclassify single-site references as patterns.
