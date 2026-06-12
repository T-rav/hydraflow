---
id: 0145
topic: architecture
source_issue: 9443
source_phase: review
created_at: 2026-06-12T14:42:30.290577+00:00
status: active
corroborations: 1
---

# Agent-dumped .likec4 diagrams must be deleted or wired to auto-regen — never preserved

Per `docs/methodology/self-documenting-architecture.md` line 92: a `.likec4` file produced in a one-shot agent run is **Generated**, not Curated. If no auto-regen loop exists, delete it.

- Allowed: file produced by `DiagramLoop` / `arch-regen.yml` on every PR.
- Not allowed: one-shot agent dump committed with no regen pipeline.

A stale diagram describing a post-fix state that doesn't exist in code is worse than no diagram — it actively misleads reviewers and operators.

**Why:** Without auto-regen, a diagram drifts from code on the next change and becomes misinformation rather than documentation.
